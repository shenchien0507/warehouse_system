"""作業登記的比對與權限規則。門檻職級在後台「職級規則」設定（apps/accounts/levels.py 的 RULES）。"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.levels import allows
from apps.personnel.models import Employee
from apps.records.models import Record

from .models import Stage, WorkEntry

# 每個階段的編號要先在哪裡出現過
SOURCE_LABEL = {Stage.PICKING: "登記紀錄", Stage.ALLOCATION: "撿貨"}


def number_exists(stage, number):
    if stage == Stage.PICKING:
        return Record.objects.filter(number=number).exists()
    return WorkEntry.objects.filter(stage=Stage.PICKING, number=number).exists()


def check_number(stage, number):
    if not number_exists(stage, number):
        raise ValidationError(f"{SOURCE_LABEL[stage]}沒有編號「{number}」，不能登記。")


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
