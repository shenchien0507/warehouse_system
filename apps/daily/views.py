"""「當日統計」：同一頁匯入（單一檔案一批，累加到作業日的資料池）和 dashboard。
dashboard 顯示最近一個有資料的作業日（或網址指定的作業日），每分鐘自動更新；明細表格收在下面可展開。"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.http import Http404
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView, View

from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.orders.models import GroupVersion, MappingVersion
from apps.orders.stats import version_groups
from apps.orders.views import summary_context
from apps.records.rules import registered_by_kind

from .batches import import_batch
from .forms import ImportForm
from .models import DailyBatch
from .stats import batch_stats, dashboard, day_stats, duplicates

REFRESH_SECONDS = 60


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
            board=dashboard(batches, total, groups, registered_by_kind(work_date)),
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
        return context


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
        batch.delete()
        messages.success(request, f"已刪除{name}。")
        if DailyBatch.objects.filter(work_date=work_date).exists():
            return redirect("daily:day_detail", work_date=work_date)
        return redirect("daily:day_list")
