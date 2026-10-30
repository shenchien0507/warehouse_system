"""「當日統計」：同一頁匯入（單一檔案一批，累加到作業日的資料池）和 dashboard。
dashboard 顯示最近一個有資料的作業日（或網址指定的作業日），每分鐘自動更新；明細表格收在下面可展開。
上方可搜尋這個作業日的訂單，有問題的訂單抽起來（不算進數字），之後手動放回或等之後的批次檔出現自動放回。"""

from urllib.parse import urlencode


from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.http import Http404
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View

from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.orders.models import GroupVersion, MappingVersion
from apps.orders.stats import version_groups
from apps.orders.views import summary_context
from apps.records.rules import registered_by_kind

from .batches import import_batch
from .forms import ImportForm
from .models import DailyBatch, DailyHold, DailyOrder
from .stats import batch_stats, dashboard, day_stats, duplicates, held_stats, order_place, other_days, search_orders

REFRESH_SECONDS = 60
SEARCH_LIMIT = 50


def back_to_day(work_date, keyword=""):
    """回到作業日的 dashboard，有搜尋關鍵字時保留搜尋結果。"""
    url = reverse("daily:day_detail", args=[work_date])
    return redirect(f"{url}?{urlencode({'q': keyword})}#daily-search" if keyword else url)


class DailyPageMixin:
    page_key = "daily-stats"

    def dispatch(self, request, *args, **kwargs):
        if not can_use(request.user, MENU_BY_KEY[self.page_key]):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_item"] = MENU_BY_KEY[self.page_key]
        return context


class DashboardView(DailyPageMixin, TemplateView):
    """GET ?partial=1 只回 dashboard 區塊，給頁面定時更新用。"""

    template_name = "daily/dashboard.html"

    def get_template_names(self):
        return ["daily/_dashboard.html"] if self.request.GET.get("partial") else [self.template_name]

    def post(self, request, *args, **kwargs):
        form = ImportForm(request.POST, request.FILES)
        if form.is_valid():
            outcome = import_batch(request.user, form.cleaned_data["work_date"], form.cleaned_data["file"])
            if outcome.batch:
                batch = outcome.batch
                text = f"已匯入 {batch}：{batch.order_count} 張訂單，新的 {batch.new_order_count} 張"
                if batch.duplicate_order_count:
                    text += f"，{batch.duplicate_order_count} 張之前的批次已經有了（標記為重複，不重複計算）"
                messages.success(request, text + "。")
                return redirect("daily:day_detail", work_date=batch.work_date)
            form.add_error("file" if outcome.file.message else None, outcome.message)
            self.outcome = outcome
        self.form = form
        return self.get(request, *args, **kwargs)

    def work_date(self):
        if "work_date" in self.kwargs:
            return self.kwargs["work_date"]
        return DailyBatch.objects.aggregate(day=Max("work_date"))["day"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            form=getattr(self, "form", None) or ImportForm(),
            outcome=getattr(self, "outcome", None),
            active_version=MappingVersion.active(),
            active_groups=GroupVersion.active(),
            refresh_seconds=REFRESH_SECONDS,
            refreshed_at=timezone.localtime(),
            partial_url=f"{self.request.path}?partial=1",
        )
        work_date = self.work_date()
        batches, total = day_stats(work_date) if work_date else ([], None)
        if not batches:
            if "work_date" in self.kwargs:
                raise Http404("這天沒有匯入過")
            return context
        groups = version_groups(batches[0].group_version)
        context.update(
            work_date=work_date,
            batches=batches,
            latest=batches[-1],
            board=dashboard(batches, total, groups, registered_by_kind(work_date), held_stats(batches, groups)),
            holds=DailyHold.objects.filter(order__work_date=work_date)
            .select_related("order__batch", "held_by", "released_by", "released_batch"),
            can_register=can_use(self.request.user, MENU_BY_KEY["records"]),
            total=summary_context(total),
            sections=[
                {
                    "batch": batch, "anchor": f"batch-{batch.seq}-stats",
                    "import_time_note": f"依這批的匯入時間 {timezone.localtime(batch.imported_at):%H:%M}",
                    **summary_context(batch_stats(batch, groups)),
                }
                for batch in batches
            ],
            duplicates=duplicates(work_date),
        )
        if not self.request.GET.get("partial"):
            context.update(self.search_context(work_date, groups))
        return context

    def search_context(self, work_date, groups):
        keyword = self.request.GET.get("q", "").strip()
        if not keyword:
            return {"keyword": ""}
        orders, more = search_orders(work_date, keyword, SEARCH_LIMIT)
        for order in orders:
            order.place = order_place(order, groups)
            order.found_lines = list(order.lines.select_related("batch").order_by("batch__seq", "row_no"))
            order.current_hold = next((h for h in order.holds.all() if h.is_held), None)
            order.moved_hold = next((h for h in order.holds.all() if h.status == DailyHold.MOVED), None)
        return {
            "keyword": keyword, "found": orders, "found_more": more, "search_limit": SEARCH_LIMIT,
            "elsewhere": [] if orders else other_days(keyword, work_date),
        }


def reopen_holds(batch):
    """刪掉的批次讓抽起的訂單自動放回（或轉過來）的，改回抽起中；那張訂單已經又抽起一次的就不動。"""
    for hold in DailyHold.objects.filter(released_batch=batch).exclude(status=DailyHold.RELEASED):
        if not hold.order.holds.filter(status=DailyHold.HELD).exists():
            hold.status, hold.released_at, hold.released_by, hold.released_batch = DailyHold.HELD, None, None, None
            hold.save(update_fields=["status", "released_at", "released_by", "released_batch"])


class BatchDeleteView(DailyPageMixin, View):
    """匯錯檔時刪掉當天最後一批（之前的批次可能已被後續批次比對過，先不開放）；
    這批的訂單已被其他作業日的批次標成重複時也不能刪，否則那些批次的重複紀錄會跟著不見。"""

    def post(self, request, *args, **kwargs):
        batch = DailyBatch.objects.filter(pk=kwargs["pk"]).first()
        if batch is None:
            # 連按兩下刪除、或頁面停在舊畫面時（別人已經刪了），第二次送出會找不到這批
            messages.warning(request, "這批已經刪除了（可能按了兩次刪除，或別人先刪了），請看最新的批次。")
            return redirect("daily:day_list")
        if not batch.is_latest:
            messages.error(request, "只能刪除當天最後一批。")
            return redirect("daily:day_detail", work_date=batch.work_date)
        if batch.referenced_later:
            messages.error(request, f"{batch}的訂單已在其他作業日的批次重複出現，要先刪掉那些批次。")
            return redirect("daily:day_detail", work_date=batch.work_date)
        work_date, name = batch.work_date, str(batch)
        with transaction.atomic():
            reopen_holds(batch)
            batch.delete()
        messages.success(request, f"已刪除{name}。")
        if DailyBatch.objects.filter(work_date=work_date).exists():
            return redirect("daily:day_detail", work_date=work_date)
        return redirect("daily:day_list")


class HoldView(DailyPageMixin, View):
    """抽起一張訂單：要填原因；已經抽起中的不重複抽。"""

    def post(self, request, *args, **kwargs):
        order = get_object_or_404(DailyOrder, pk=kwargs["pk"])
        keyword = request.POST.get("q", "")
        reason = request.POST.get("reason", "").strip()[: DailyHold._meta.get_field("reason").max_length]
        if not reason:
            messages.error(request, f"抽起訂單 {order.order_no} 要填原因。")
        elif order.holds.filter(status__in=DailyHold.EXCLUDED).exists():
            messages.warning(request, f"訂單 {order.order_no} 已經抽起了。")
        else:
            try:
                with transaction.atomic():
                    DailyHold.objects.create(order=order, reason=reason, held_by=request.user)
            except IntegrityError:  # 連按兩下：另一次已經抽起
                messages.warning(request, f"訂單 {order.order_no} 已經抽起了。")
            else:
                messages.success(request, f"已抽起訂單 {order.order_no}，不算進當日統計。")
        return back_to_day(order.work_date, keyword)


class ReleaseView(DailyPageMixin, View):
    """手動放回抽起中的訂單，數字算回原本的批次和分組。"""

    def post(self, request, *args, **kwargs):
        hold = get_object_or_404(DailyHold.objects.select_related("order"), pk=kwargs["pk"])
        keyword = request.POST.get("q", "")
        if hold.is_held and not hold.can_release:
            messages.error(
                request, f"訂單 {hold.order.order_no} 的作業日已經過了，不能手動放回；之後的訂單檔出現這張單時，會自動轉到那天算。"
            )
        elif hold.is_held:
            hold.close(DailyHold.RELEASED, request.user)
            messages.success(request, f"已放回訂單 {hold.order.order_no}。")
        else:
            messages.warning(request, f"訂單 {hold.order.order_no} 已經不是抽起中（{hold.outcome}）。")
        return back_to_day(hold.order.work_date, keyword)
