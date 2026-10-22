"""到班紀錄的新增、作廢，以及工位安排頁用的異動與時間軸。"""

import datetime

from django.db import transaction
from django.utils import timezone

from .models import IN_KINDS, OUT_KINDS, Attendance, AttendanceEvent, EventKind, StationBatch


def now_minute():
    return timezone.localtime().time().replace(second=0, microsecond=0)


def check_event(events, date, kind, time):
    """新紀錄和當天已有的紀錄是否衝突；沒問題回傳空字串。"""
    kinds = {e.kind for e in events}
    presence = [e for e in events if e.kind in IN_KINDS + OUT_KINDS]
    last = presence[-1] if presence else None
    on_site = last is not None and last.kind in IN_KINDS
    if kind == EventKind.ABSENT:
        if EventKind.ABSENT in kinds:
            return "這天已經標記缺勤。"
        if kinds:
            return "這天已有上班或請假紀錄，不能標記缺勤。"
        return ""
    if EventKind.ABSENT in kinds:
        return "這天已標記缺勤，要先作廢「缺勤」才能登記其他紀錄。"
    if kind in IN_KINDS and on_site:
        return f"已在 {last.time:%H:%M} 上班，還沒離開。"
    if kind in OUT_KINDS and not on_site:
        return "還沒有上班，請先登記上班。"
    if kind in IN_KINDS + OUT_KINDS:
        if last and time < last.time:
            return f"時間不能早於上一筆進出紀錄（{last.describe()}）。"
        if date == timezone.localdate() and time > now_minute():
            return "不能登記還沒到的時間。"
    return ""


def add_event(employee, date, user, kind, time=None, end_time=None, note=""):
    """新增一筆紀錄並重算當天狀態；回傳 (到班紀錄, 錯誤訊息)。"""
    with transaction.atomic():
        record = Attendance.objects.select_for_update().filter(employee=employee, date=date).first()
        error = check_event(record.active_events() if record else [], date, kind, time)
        if error:
            return record, error
        if record is None:
            record = Attendance.objects.create(employee=employee, date=date, created_by=user, updated_by=user)
        AttendanceEvent.objects.create(attendance=record, kind=kind, time=time, end_time=end_time, note=note, created_by=user)
        record.updated_by = user
        record.refresh()
        record.save()
    return record, ""


def void_event(event, user):
    with transaction.atomic():
        event.voided_by, event.voided_at = user, timezone.now()
        event.save(update_fields=["voided_by", "voided_at"])
        record = event.attendance
        record.updated_by = user
        record.refresh()
        record.save()


def person(employee):
    return f"{employee.name}（{employee.department.name}）" if employee.department else employee.name


def batch_diff(entries, previous):
    """和上一批比：人數增減、離開、新到、換工位人數。previous 為 None 代表當天第一批。"""
    if previous is None:
        return None
    now = {e.employee_id: e for e in entries}
    before = {e.employee_id: e for e in previous}
    return {
        "delta": len(now) - len(before),
        "left": [e.employee for k, e in before.items() if k not in now],
        "arrived": [e.employee for k, e in now.items() if k not in before],
        "moved": sum(1 for k, e in now.items() if k in before and before[k].station_id != e.station_id),
    }


def changes_since(date, batch_entries, on_site_records):
    """目前生效的批次之後，誰離開、誰新到；依時間排列，例如「11:00 王小華（出貨）請假離開」。"""
    in_batch = {e.employee_id: e.employee for e in batch_entries}
    here = {r.employee_id: r.employee for r in on_site_records}
    moved = {k: v for k, v in in_batch.items() if k not in here} | {k: v for k, v in here.items() if k not in in_batch}
    records = {
        r.employee_id: r for r in Attendance.objects.filter(date=date, employee_id__in=moved).prefetch_related("events")
    }
    items = []
    for pk, employee in moved.items():
        kinds = OUT_KINDS if pk in in_batch else IN_KINDS
        found = [e for e in records[pk].active_events() if e.kind in kinds] if pk in records else []
        time, label = (found[-1].time, found[-1].get_kind_display()) if found else (None, "已不在現場")
        items.append({"time": time, "text": f"{person(employee)} {label}", "kind": "out" if pk in in_batch else "in"})
    items.sort(key=lambda i: i["time"] or datetime.time.min)
    return items


def timeline(date, can_see):
    """當天的上班、離開、請假、缺勤與建立安排，依時間排列，附上每一步之後的在場人數。
    同一分鐘多人上班（或下班）合併成一行。"""
    events = [
        e
        for e in AttendanceEvent.objects.filter(attendance__date=date, voided_at__isnull=True).select_related(
            "attendance__employee__department", "created_by"
        )
        if can_see(e.attendance.employee)
    ]
    rows = [((e.time or datetime.time.min), 0, e.created_at, e) for e in events]
    batches = StationBatch.objects.filter(date=date).select_related("created_by").prefetch_related("entries__employee")
    for batch in batches:
        entries = [x for x in batch.entries.all() if can_see(x.employee)]
        if entries:
            rows.append((timezone.localtime(batch.created_at).time(), 1, batch.created_at, (batch, entries)))
    rows.sort(key=lambda r: r[:3])
    latest = max((r[3][0] for r in rows if r[1] == 1), key=lambda b: (b.created_at, b.pk), default=None)

    here, items = set(), []
    for time, is_batch, _, obj in rows:
        if is_batch:
            batch, entries = obj
            items.append({
                "time": time, "kind": "batch", "text": f"建立安排（{len(entries)} 人）",
                "by": batch.created_by, "current": batch == latest, "count": len(here),
            })
            continue
        event, employee = obj, obj.attendance.employee
        if event.kind in IN_KINDS:
            here.add(employee.pk)
        elif event.kind in OUT_KINDS:
            here.discard(employee.pk)
        kind = "in" if event.kind in IN_KINDS else "out" if event.kind in OUT_KINDS else "leave"
        previous = items[-1] if items else None
        if (
            event.kind in (EventKind.CLOCK_IN, EventKind.CLOCK_OUT)
            and previous
            and previous.get("event_kind") == event.kind
            and previous["time"] == event.time
        ):
            previous["people"].append(employee)
            previous["text"] = f"{len(previous['people'])} 人{event.get_kind_display()}"
            previous["count"] = len(here)
            continue
        text = f"{person(employee)} {event.describe() if event.kind == EventKind.LEAVE else event.get_kind_display()}"
        if event.note:
            text += f"，{event.note}"
        items.append({
            "time": event.time, "kind": kind, "event_kind": event.kind, "people": [employee], "text": text,
            "by": event.created_by, "count": len(here),
        })
    return items
