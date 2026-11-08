"""到班登記的範圍與修改規則。門檻職級在後台「職級規則」設定（apps/accounts/levels.py 的 RULES）。"""

from django.utils import timezone

from apps.accounts.levels import allows
from apps.personnel.models import Employee


def can_register_any(user):
    """符合「登記人員」規則的人可以登記所有人員（到班人數與名單也是這個範圍）。"""
    return allows(user, "attendance-register")


def employees_in_scope(user):
    return Employee.objects.all() if can_register_any(user) else Employee.objects.none()


def can_register(user, employee):
    return can_register_any(user)


def can_add(user, date):
    """今天：範圍內的人員任何有登記權的人都能新增紀錄；之前的日期依「修改之前日期」規則；不能登記未來日期。"""
    today = timezone.localdate()
    if date > today:
        return False
    return date == today or allows(user, "attendance-past-dates")


def can_void(user, event):
    """今天只能作廢自己登記的紀錄；之前的日期、或作廢別人登記的，依「修改之前日期」規則。"""
    date = event.attendance.date
    if date > timezone.localdate() or event.voided_at:
        return False
    if allows(user, "attendance-past-dates"):
        return True
    return date == timezone.localdate() and event.created_by_id == user.pk


def can_arrange(user, date):
    """工位不鎖定：當天隨時可改；之前的日期依「修改之前日期」規則；不能安排未來日期。"""
    today = timezone.localdate()
    if date > today:
        return False
    return date == today or allows(user, "attendance-past-dates")
