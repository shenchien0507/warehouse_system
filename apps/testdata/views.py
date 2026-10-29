"""「測試資料產生」：設定好之後按生成，直接下載 zip（每種類型一個 Excel）。不寫進資料庫。
「訂單流模擬」一步一步模擬訂單流進新訂單、分批整理正式訂單（見 simulation.py）。
這是暫時的功能，正式開發完成後整個 apps/testdata 移除（另外刪 settings、urls、選單各一行）。"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.generic import FormView, TemplateView, View

from apps.backoffice.menu import MENU_BY_KEY, can_use

from . import simulation
from .forms import AdvanceForm, GenerateForm, ReleaseForm, SimulationStartForm
from .generator import generate, zip_bytes

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def download(content, name, content_type):
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = content_disposition_header(True, name)
    return response


def now():
    return timezone.localtime().replace(tzinfo=None, microsecond=0)


def load_caught_up():
    """讀進度；跟著現在時間走的模擬先補上到現在為止流進來的單，截斷時間就是現在。"""
    state = simulation.load()
    if state and state["live"] and simulation.advance(state, now()):
        simulation.save(state)
    return state


class TestDataPageMixin:
    page_key = "test-data"

    def dispatch(self, request, *args, **kwargs):
        if not can_use(request.user, MENU_BY_KEY[self.page_key]):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class GenerateView(TestDataPageMixin, FormView):
    template_name = "testdata/generate.html"
    form_class = GenerateForm

    def form_valid(self, form):
        data = form.cleaned_data
        files = generate(data["settings"], data["options"], data["first_order_no"])
        stamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        return download(zip_bytes(files, stamp), f"測試資料_{stamp}.zip", "application/zip")


class SimulateView(TestDataPageMixin, TemplateView):
    """訂單流模擬：沒有進行中的模擬時顯示開始表單；有的話顯示目前時間、各池子張數、各輪正式訂單，以及推進、產生正式訂單等操作。
    跟著現在時間走的模擬，每次打開頁面都先補上到現在為止流進來的單。"""

    template_name = "testdata/simulate.html"

    def get(self, request, *args, **kwargs):
        self.state = load_caught_up()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.state = load_caught_up()
        action = request.POST.get("action")
        if action == "start" and not self.state:
            form = SimulationStartForm(request.POST)
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(start_form=form))
            data = form.cleaned_data
            state = simulation.start(data["start"], data["live"], data["orders_per_day"], data["urgent_pct"],
                                     data["shipping_pct"], data["options"], data["first_order_no"])
            if data["live"]:
                simulation.advance(state, now())
            simulation.save(state)
            messages.success(request, "模擬開始了。")
        elif action == "reset":
            simulation.reset()
            messages.success(request, "已經清掉這個模擬，可以重新開始。")
        elif not self.state:
            messages.error(request, "目前沒有進行中的模擬。")
        elif action == "advance" and not self.state["live"]:
            form = AdvanceForm(request.POST, clock=simulation.parse(self.state["clock"]))
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(advance_form=form))
            added = simulation.advance(self.state, form.cleaned_data["to"])
            simulation.save(self.state)
            messages.success(request, f"時間推進到 {self.state['clock']}，流進來 {added} 張新單。")
        elif action == "release":
            form = ReleaseForm(request.POST)
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(release_form=form))
            if not simulation.cut_orders(self.state):
                messages.error(request, "截斷的池子裡沒有訂單可以出。")
            else:
                entry = simulation.release(self.state, form.cleaned_data["count"])
                simulation.save(self.state)
                messages.success(request, f"第 {entry['no']} 輪正式訂單：{len(entry['order_nos'])} 張，可以在下面下載。")
        elif action == "undo" and self.state["rounds"]:
            entry = simulation.undo(self.state)
            simulation.save(self.state)
            messages.success(request, f"已撤銷第 {entry['no']} 輪，那些單退回原本的位置。")
        return redirect("testdata:simulate")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not self.state:
            context.setdefault("start_form", SimulationStartForm())
            return context
        summary = simulation.summary(self.state)
        context.update(
            state=self.state, summary=summary,
            advance_form=kwargs.get("advance_form") or AdvanceForm(clock=summary["clock"]),
            release_form=kwargs.get("release_form") or ReleaseForm(),
            quick_minutes=[(30, "+30 分"), (60, "+1 小時"), (120, "+2 小時"), (240, "+4 小時")],
        )
        return context


class PoolsDownloadView(TestDataPageMixin, View):
    """下載目前的新訂單、急單、出貨中（zip）。"""

    def get(self, request):
        state = load_caught_up()
        if not state:
            raise Http404
        content, name = simulation.pools_zip(state)
        simulation.save(state)
        return download(content, name, "application/zip")


class RoundDownloadView(TestDataPageMixin, View):
    """下載某一輪的正式訂單。"""

    def get(self, request, round_no):
        state = simulation.load()
        if not state or not any(r["no"] == round_no for r in state["rounds"]):
            raise Http404
        content, name = simulation.round_file(state, round_no)
        return download(content, name, XLSX)
