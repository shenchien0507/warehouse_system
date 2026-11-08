"""「日結」頁：看目前作業日的數字和還沒處理的事項，主任以上（職級規則「日結」）按日結或取消日結；下面列出之前的日結報表。"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import DetailView, TemplateView, View

from apps.accounts.levels import allows
from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.daily.models import DailyBatch, DailyHold
from apps.records.models import Record
from apps.worklog.models import Stage, WorkEntry

from .carry import carry_report, snapshot
from .models import DayClose
from .workday import carry_start, current_work_date, last_close

PAGE_KEY = "day-close"
RULE = "day-close"


class ClosingPageMixin:
    def dispatch(self, request, *args, **kwargs):
        if not can_use(request.user, MENU_BY_KEY[PAGE_KEY]):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(menu_item=MENU_BY_KEY[PAGE_KEY], can_close=allows(self.request.user, RULE))
        return context


def checks(day):
    """日結前要看一下的事項：[(文字, 數量)]，數量 0 的不列。不會擋日結，只是讓人知道會轉到隔天。"""
    items = [
        ("還有抽起中的訂單（不算進數字，放回前一直是抽起）", DailyHold.objects.filter(status=DailyHold.HELD).count()),
        ("撿貨開始了還沒刷結束的編號", WorkEntry.objects.filter(stage=Stage.PICKING, ended_at__isnull=True).count()),
        ("配貨開始了還沒刷結束的編號", WorkEntry.objects.filter(stage=Stage.ALLOCATION, ended_at__isnull=True).count()),
    ]
    rows = [(text, count) for text, count in items if count]
    if not DailyBatch.objects.filter(work_date=day).exists():
        rows.insert(0, ("這個作業日還沒匯入當日統計", None))
    return rows


def kind_totals(kinds):
    return {key: sum(k.get(key, 0) for k in kinds) for key in ("today", "carried", "done", "unprinted", "picking", "packing")}


def changed_after(close):
    """日結之後，那天的登記紀錄或配貨完成又被改過（日結報表的數字不會跟著變）。"""
    return (
        Record.objects.filter(work_date=close.work_date, updated_at__gt=close.closed_at).exists()
        or WorkEntry.objects.filter(end_work_date=close.work_date, updated_at__gt=close.closed_at).exists()
    )


class ClosingView(ClosingPageMixin, TemplateView):
    template_name = "closing/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start = carry_start()
        context["carry_start"] = start
        if start is None:
            return context
        day = current_work_date()
        latest = last_close()
        context.update(
            work_date=day,
            today=timezone.localdate(),
            overdue=day < timezone.localdate(),
            early=day > timezone.localdate(),
            preview=(preview := snapshot(day)["kinds"]),
            preview_totals=kind_totals(preview),
            checks=checks(day),
            carry=carry_report(day),
            latest=latest,
            closes=DayClose.objects.filter(work_date__gte=start).select_related("closed_by")[:30],
        )
        return context


class CloseDayView(ClosingPageMixin, View):
    """日結目前的作業日。表單帶著頁面上的作業日，和現在的不一樣（別人剛日結過）就不做。"""

    def post(self, request, *args, **kwargs):
        if not allows(request.user, RULE):
            raise PermissionDenied
        if carry_start() is None:
            messages.error(request, "還沒設定結轉起算日，不用日結。")
            return redirect("closing:index")
        day = current_work_date()
        if request.POST.get("work_date") != day.isoformat():
            messages.warning(request, f"作業日已經換成 {day:%Y/%m/%d}（可能別人剛日結過），請看過最新的數字再按。")
            return redirect("closing:index")
        if day > timezone.localdate():
            messages.error(request, f"{day:%Y/%m/%d} 還沒到，不能日結。")
            return redirect("closing:index")
        try:
            with transaction.atomic():
                close = DayClose.objects.create(work_date=day, closed_by=request.user, snapshot=snapshot(day))
        except IntegrityError:
            messages.warning(request, f"{day:%Y/%m/%d} 已經日結過了。")
            return redirect("closing:index")
        messages.success(request, f"已日結 {day:%Y/%m/%d}，沒做完的會轉到下一個作業日。")
        return redirect("closing:report", work_date=close.work_date)


class CancelCloseView(ClosingPageMixin, View):
    """取消最近一次日結（太早按了）：只能取消最後一天，取消後那天變回目前的作業日，補完再重按。"""

    def post(self, request, *args, **kwargs):
        if not allows(request.user, RULE):
            raise PermissionDenied
        close = get_object_or_404(DayClose, work_date=kwargs["work_date"])
        if close != last_close():
            messages.error(request, "只能取消最近一次日結。")
            return redirect("closing:index")
        close.delete()
        messages.success(request, f"已取消 {close.work_date:%Y/%m/%d} 的日結，作業日回到這天。")
        return redirect("closing:index")


class ReportView(ClosingPageMixin, DetailView):
    template_name = "closing/report.html"
    context_object_name = "close"

    def get_object(self, queryset=None):
        return get_object_or_404(DayClose.objects.select_related("closed_by"), work_date=self.kwargs["work_date"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        close = self.object
        context.update(
            changed=changed_after(close),
            is_latest=close == last_close(),
            totals=kind_totals(close.kinds),
        )
        return context
