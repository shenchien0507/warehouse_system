"""目前的作業日。

後台「撿貨配貨設定」沒填結轉起算日（或還沒到那天）：作業日就是系統日期的今天，和以前一樣。
填了之後：作業日要按「日結」才結束，做到半夜 12 點以後也還是同一個作業日。
目前的作業日 = 最後一次日結的隔天起，最早一個已經有資料（當日統計匯入、登記紀錄、配貨完成）的日子；
還沒有任何資料時就是今天（但不會早於最後一次日結的隔天）。"""

from datetime import timedelta

from django.utils import timezone


def carry_start():
    """結轉起算日；沒填或還沒到那天回傳 None（不結轉、不用日結）。"""
    from apps.worklog.models import WorklogSetting

    start = WorklogSetting.objects.filter(pk=1).values_list("carry_start", flat=True).first()
    if start is None or start > timezone.localdate():
        return None
    return start


def last_close(before=None):
    """起算日以後最後一次日結（before 有值就是那天之前的最後一次）；沒有回傳 None。"""
    from .models import DayClose

    start = carry_start()
    if start is None:
        return None
    closes = DayClose.objects.filter(work_date__gte=start)
    if before is not None:
        closes = closes.filter(work_date__lt=before)
    return closes.order_by("-work_date").first()


def current_work_date():
    today = timezone.localdate()
    start = carry_start()
    if start is None:
        return today
    from apps.daily.models import DailyBatch
    from apps.records.models import Record
    from apps.worklog.models import WorkEntry

    close = last_close()
    floor = close.work_date + timedelta(days=1) if close else start
    days = [
        model.objects.filter(**{f"{field}__gte": floor}).order_by(field).values_list(field, flat=True).first()
        for model, field in [(DailyBatch, "work_date"), (Record, "work_date"), (WorkEntry, "end_work_date")]
    ]
    days = [day for day in days if day is not None]
    return min(days) if days else max(floor, today)


def carry_on():
    return carry_start() is not None
