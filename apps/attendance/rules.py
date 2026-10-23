"""到班登記的範圍與修改規則。門檻職級在後台「職級規則」設定（apps/accounts/levels.py 的 RULES）。"""

from django.utils import timezone

from apps.accounts.levels import allows
from apps.accounts.models import Department


def departments_in_scope(user):
    """可登記全部部門的人看全部；可登記自己部門的人只看自己部門；其他人不能登記。"""
    if allows(user, "attendance-register-all"):
        return Department.objects.order_by("name")
    if allows(user, "attendance-register-own") and user.department_id:
        return Department.objects.filter(pk=user.department_id)
    return Department.objects.none()


def can_register(user, employee):
    if allows(user, "attendance-register-all"):
        return True
    return allows(user, "attendance-register-own") and bool(user.department_id) and employee.department_id == user.department_id


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


def station_departments(user):
    """工位安排的範圍：能不能進這頁由頁面權限決定；可安排全部部門的人看全部，其他人只能安排自己的部門。"""
    if allows(user, "attendance-stations-all"):
        return Department.objects.order_by("name")
    if user.department_id:
        return Department.objects.filter(pk=user.department_id)
    return Department.objects.none()


def can_arrange(user, date):
    """工位不鎖定：當天隨時可改；之前的日期依「修改之前日期」規則；不能安排未來日期。"""
    today = timezone.localdate()
    if date > today:
        return False
    return date == today or allows(user, "attendance-past-dates")
