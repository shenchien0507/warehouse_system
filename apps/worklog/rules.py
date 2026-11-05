"""作業登記的比對與權限規則。門檻職級在後台「職級規則」設定（apps/accounts/levels.py 的 RULES）。"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.levels import allows
from apps.attendance.models import Attendance
from apps.personnel.models import Employee
from apps.records.models import Record

from .models import Stage, WorkEntry, WorklogSetting, WorkSegment

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
    segment = last.segments.order_by("-started_at", "-pk").first()
    if last.ended_at:
        last_time, action = last.ended_at, "結束"
    elif segment is not None and segment.started_at > last.started_at:
        last_time, action = segment.started_at, "接手"
    else:
        last_time, action = last.started_at, "開始"
    elapsed = (timezone.now() - last_time).total_seconds()
    if elapsed < seconds:
        raise ValidationError(
            f"編號「{number}」{int(elapsed)} 秒前剛刷過{action}，{seconds} 秒內再刷不算（可能是重複刷了），要記下一步請 {seconds - int(elapsed)} 秒後再刷。"
        )


def find_employee(employee_no):
    """員工編號要對得到在職的人員資料工號。"""
    employee = Employee.objects.filter(employee_no=employee_no, is_active=True).first()
    if employee is None:
        raise ValidationError(f"人員資料沒有在職的員工編號「{employee_no}」，不能登記。")
    return employee


def check_station(stage, employee, date=None):
    """設定裡這個階段有勾工位，員工那天（預設今天）的工位就要是其中一個，沒排工位或沒到班也擋下。
    工位看到班紀錄的「當日工位」，也就是工位安排目前生效那批的結果。"""
    allowed = WorklogSetting.load().stations_for(stage)
    if not allowed:
        return
    date = date or timezone.localdate()
    attendance = Attendance.objects.filter(employee=employee, date=date).select_related("station").first()
    station = attendance.station if attendance else None
    if station is None or station.pk not in {s.pk for s in allowed}:
        now = station.name if station else ("未安排" if attendance else "今天沒有到班紀錄")
        names = "、".join(s.name for s in allowed)
        label = Stage(stage).label
        raise ValidationError(
            f"{employee.employee_no} {employee.name} 今天的工位是「{now}」，{label}只有工位是「{names}」的人可以登記。"
        )


def open_entry(stage, number, exclude=None):
    entries = WorkEntry.objects.filter(stage=stage, number=number, ended_at__isnull=True)
    if exclude is not None:
        entries = entries.exclude(pk=exclude.pk)
    return entries.first()


def scan(stage, number, employee, user):
    """刷一次，回傳 (紀錄, 動作)，動作是 "start"、"handover" 或 "end"：
    - 同編號沒有還沒結束的：開一筆新的（第一段是這個人）
    - 有還沒結束的，而且是目前負責的人刷：完成
    - 有還沒結束的，換別人刷：交接，前一段記成交接，這個人開新的一段，等他再刷一次才完成"""
    now = timezone.now()
    with transaction.atomic():
        entry = (
            WorkEntry.objects.select_for_update()
            .filter(stage=stage, number=number, ended_at__isnull=True)
            .first()
        )
        if entry is None:
            anomaly = stage == Stage.ALLOCATION and open_entry(Stage.PICKING, number) is not None
            entry = WorkEntry.objects.create(
                stage=stage, number=number, start_employee=employee, anomaly=anomaly, created_by=user
            )
            WorkSegment.objects.create(entry=entry, employee=employee, started_at=entry.started_at)
            return entry, "start"
        segment = entry.segments.filter(ended_at__isnull=True).order_by("-started_at", "-pk").first()
        if segment is None:  # 理論上不會發生（每筆至少一段）；補一段給原本開始的人
            segment = WorkSegment.objects.create(entry=entry, employee=entry.start_employee, started_at=entry.started_at)
        if segment.employee_id == employee.pk:
            segment.ended_at, segment.outcome = now, WorkSegment.DONE
            segment.save(update_fields=["ended_at", "outcome"])
            entry.end_employee, entry.ended_at = employee, now
            entry.save(update_fields=["end_employee", "ended_at"])
            return entry, "end"
        segment.ended_at, segment.outcome = now, WorkSegment.HANDOVER
        segment.save(update_fields=["ended_at", "outcome"])
        WorkSegment.objects.create(entry=entry, employee=employee, started_at=now)
        entry.handover_from = segment.employee
        return entry, "handover"


def sync_segments(entry):
    """修改登記的開始、結束員工後，第一段、最後一段（已完成的話）的員工跟著改。"""
    segments = list(entry.segments.order_by("started_at", "pk"))
    if not segments:
        return
    first, last = segments[0], segments[-1]
    if first.employee_id != entry.start_employee_id:
        first.employee_id = entry.start_employee_id
        first.save(update_fields=["employee"])
    if entry.ended_at and last.employee_id != entry.end_employee_id:
        last.employee_id = entry.end_employee_id
        last.save(update_fields=["employee"])


def can_edit(user, entry):
    """自己帳號登記的可以修改、刪除；別人的依「作業登記：修改、刪除別人登記的紀錄」規則（預設主任以上）。"""
    return entry.created_by_id == user.pk or allows(user, "worklog-edit-all")


def can_see_anomaly(user):
    return allows(user, "worklog-see-anomaly")
