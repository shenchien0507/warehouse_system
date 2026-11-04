"""「訂單統計」：一次匯入多個分類的檔案，各分類一張表，最後合計。"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import DetailView, ListView, View

from apps.backoffice.menu import MENU_BY_KEY, can_use

from .batches import check_versions, import_run, read_file
from .forms import ImportForm
from .models import GroupVersion, ImportCategory, MappingVersion, StatRun
from .stats import run_stats


class StatsPageMixin:
    page_key = "order-stats"

    def dispatch(self, request, *args, **kwargs):
        if not can_use(request.user, MENU_BY_KEY[self.page_key]):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_item"] = MENU_BY_KEY[self.page_key]
        return context


class CheckFileView(StatsPageMixin, View):
    """選好檔案當下先試讀一次（和匯入用同一套檢查），不寫入任何資料；回傳 JSON 給匯入頁顯示。"""

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return JsonResponse({"ok": False, "message": "沒有收到檔案。"})
        version, _, message = check_versions()
        if message:
            return JsonResponse({"ok": False, "message": message})
        result, outcome = read_file(version, uploaded)
        if outcome.message:
            errors = [[row_no, label, str(raw), error] for row_no, label, raw, error in outcome.errors]
            return JsonResponse({"ok": False, "message": outcome.message, "errors": errors, "error_count": outcome.error_count})
        orders = len({values["order_no"] for _, values in result.lines})
        return JsonResponse({"ok": True, "message": f"檢查沒問題：{orders} 張訂單、{len(result.lines)} 列。"})


class RunListView(StatsPageMixin, ListView):
    """匯入（每個分類各放一份檔案）與歷次統計紀錄；匯入成功就直接到這筆的統計。"""

    template_name = "orders/run_list.html"
    queryset = StatRun.objects.select_related("created_by").prefetch_related("batches")
    paginate_by = 20

    def categories(self):
        return ImportCategory.objects.filter(is_active=True)

    def post(self, request, *args, **kwargs):
        form = ImportForm(request.POST, request.FILES, categories=self.categories())
        if form.is_valid():
            outcome = import_run(request.user, form.cleaned_data["work_date"], form.files_to_import())
            if outcome.run:
                batches = outcome.run.batches.all()
                text = "、".join(f"{b.category_name} {b.order_count} 張" for b in batches)
                messages.success(request, f"已匯入 {len(batches)} 份檔案：{text}。")
                return redirect("orders:run_detail", pk=outcome.run.pk)
            form.add_error(None, outcome.message)
            for category, problem in outcome.files:
                form.add_error(form.file_field(category), problem.message)
            self.outcome = outcome
        self.form = form
        return self.get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = getattr(self, "form", None) or ImportForm(categories=self.categories())
        context["outcome"] = getattr(self, "outcome", None)
        context["active_version"] = MappingVersion.active()
        context["active_groups"] = GroupVersion.active()
        return context


def summary_context(summary):
    dated = [day for day in summary.days if day]
    first, last = (dated[0], dated[-1]) if dated else (None, None)
    return {"summary": summary, "by_import_time": len(summary.by_import_time), "first_day": first, "last_day": last}


class RunDetailView(StatsPageMixin, DetailView):
    template_name = "orders/run_detail.html"
    queryset = StatRun.objects.select_related("created_by")
    context_object_name = "run"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sections, total = run_stats(self.object)
        context["sections"] = [
            {"batch": batch, "anchor": f"category-{i}", **summary_context(summary)} for i, (batch, summary) in enumerate(sections, start=1)
        ]
        context["total"] = summary_context(total)
        context["first_batch"] = sections[0][0] if sections else None
        return context


class RunDeleteView(StatsPageMixin, View):
    """匯入錯檔案時刪掉整筆統計紀錄（所有分類的檔案一起刪）。"""

    def post(self, request, *args, **kwargs):
        run = get_object_or_404(StatRun, pk=kwargs["pk"])
        name = str(run)
        run.delete()
        messages.success(request, f"已刪除統計紀錄 {name}。")
        return redirect("orders:run_list")
