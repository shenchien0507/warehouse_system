"""作業登記的比對與權限規則。門檻職級在後台「職級規則」設定（apps/accounts/levels.py 的 RULES）。"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.levels import allows
from apps.personnel.models import Employee
from apps.records.models import Record

from .models import Stage, WorkEntry, WorklogSetting

# 每個階段的編號要先在哪裡出現過
SOURCE_LABEL = {Stage.PICKING: "登記紀錄", Stage.ALLOCATION: "撿貨"}


def source_number(stage, number):
    """編號在來源（撿貨看登記紀錄、配貨看撿貨）存的寫法；沒有回傳 None。
    MySQL 比對不分大小寫，s-001 也對得到 S-001，存來源的寫法，數據塔才對得起來。"""
    if stage == Stage.PICKING:
        numbers = Record.objects.filter(number=number)
    else:
        numbers = WorkEntry.objects.filter(stage=Stage.PICKING, number=number)
    return numbers.values_list("number", flat=True).first()


def check_number(stage, number):
    """回傳來源的編號寫法；沒有就擋下。"""
    found = source_number(stage, number)
    if found is None:
        raise ValidationError(f"{SOURCE_LABEL[stage]}沒有編號「{number}」，不能登記。")
    return found


def check_cycle(stage, number):
    """每個編號照順序只走一輪：撿貨開始 → 撿貨結束 → 配貨開始 → 配貨結束。
    這個階段已經走完（或撿貨時已經進到配貨）就擋下，說明下一步；要重做請把舊的登記刪掉（自己的，或主任以上）。"""
    entries = WorkEntry.objects.filter(number=number)
    if entries.filter(stage=stage, ended_at__isnull=True).exists():
        return  # 這次是刷結束
    if stage == Stage.PICKING and entries.filter(stage=Stage.ALLOCATION).exists():
        raise ValidationError(f"編號「{number}」已經進到配貨，不能再撿貨；要重做請先刪掉舊的登記。")
    if entries.filter(stage=stage).exists():
        done = "撿貨已經結束，下一步是配貨" if stage == Stage.PICKING else "配貨已經完成"
        raise ValidationError(f"編號「{number}」{done}，不能再登記一輪；要重做請先刪掉舊的登記。")


def check_rescan(stage, number):
    """同一個編號在這個階段最後一次刷（開始或結束）不到設定的秒數，就擋下，避免連刷直接記結束。"""
    seconds = WorklogSetting.load().rescan_seconds
    last = WorkEntry.objects.filter(stage=stage, number=number).order_by("-started_at", "-pk").first()
    if not seconds or last is None:
        return
    elapsed = (timezone.now() - (last.ended_at or last.started_at)).total_seconds()
    if elapsed < seconds:
        action = "結束" if last.ended_at else "開始"
        raise ValidationError(
            f"編號「{number}」{int(elapsed)} 秒前剛刷過{action}，{seconds} 秒內再刷不算（可能是重複刷了），要記下一步請 {seconds - int(elapsed)} 秒後再刷。"
        )


def find_employee(employee_no):
    """員工編號要對得到在職的人員資料工號。"""
    employee = Employee.objects.filter(employee_no=employee_no, is_active=True).first()
    if employee is None:
        raise ValidationError(f"人員資料沒有在職的員工編號「{employee_no}」，不能登記。")
    return employee


def open_entry(stage, number, exclude=None):
    entries = WorkEntry.objects.filter(stage=stage, number=number, ended_at__isnull=True)
    if exclude is not None:
        entries = entries.exclude(pk=exclude.pk)
    return entries.first()


def scan(stage, number, employee, user):
    """刷一次：同編號有還沒結束的就記結束，沒有就開一筆新的。回傳 (紀錄, 是否為開始)。"""
    with transaction.atomic():
        entry = (
            WorkEntry.objects.select_for_update()
            .filter(stage=stage, number=number, ended_at__isnull=True)
            .first()
        )
        if entry is not None:
            entry.end_employee, entry.ended_at = employee, timezone.now()
            entry.save(update_fields=["end_employee", "ended_at"])
            return entry, False
        anomaly = stage == Stage.ALLOCATION and open_entry(Stage.PICKING, number) is not None
        entry = WorkEntry.objects.create(
            stage=stage, number=number, start_employee=employee, anomaly=anomaly, created_by=user
        )
        return entry, True


def can_edit(user, entry):
    """自己帳號登記的可以修改、刪除；別人的依「作業登記：修改、刪除別人登記的紀錄」規則（預設主任以上）。"""
    return entry.created_by_id == user.pk or allows(user, "worklog-edit-all")


def can_see_anomaly(user):
    return allows(user, "worklog-see-anomaly")
