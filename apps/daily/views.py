"""「當日統計」：每批單一檔案匯入，累加到作業日的資料池；當日累計一張表，下面是每批的明細與重複的訂單。"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import ListView, TemplateView, View

from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.orders.models import GroupVersion, MappingVersion
from apps.orders.stats import version_groups
from apps.orders.views import summary_context

from .batches import import_batch
from .forms import ImportForm
from .models import DailyBatch
from .stats import batch_stats, day_stats, duplicates


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


class DayListView(DailyPageMixin, ListView):
    """匯入一批（單一檔案）與每個作業日的累計；匯入成功就到那天的當日統計。"""

    template_name = "daily/day_list.html"
    paginate_by = 20

    def get_queryset(self):
        return (
            DailyBatch.objects.values("work_date")
            .annotate(batch_count=Count("pk"), order_count=Sum("new_order_count"), last_import=Max("imported_at"))
            .order_by("-work_date")
        )

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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = getattr(self, "form", None) or ImportForm()
        context["outcome"] = getattr(self, "outcome", None)
        context["active_version"] = MappingVersion.active()
        context["active_groups"] = GroupVersion.active()
        return context


class DayDetailView(DailyPageMixin, TemplateView):
    template_name = "daily/day_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        work_date = kwargs["work_date"]
        batches, total = day_stats(work_date)
        if not batches:
            raise Http404("這天沒有匯入過")
        groups = version_groups(batches[0].group_version)
        context.update(
            work_date=work_date,
            batches=batches,
            latest=batches[-1],
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
            order_total=sum(b.new_order_count for b in batches),
        )
        return context


class BatchDeleteView(DailyPageMixin, View):
    """匯錯檔時刪掉當天最後一批（之前的批次可能已被後續批次比對過，先不開放）；
    這批的訂單已被其他作業日的批次標成重複時也不能刪，否則那些批次的重複紀錄會跟著不見。"""

    def post(self, request, *args, **kwargs):
        batch = get_object_or_404(DailyBatch, pk=kwargs["pk"])
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
