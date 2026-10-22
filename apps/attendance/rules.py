"""到班登記的範圍與修改規則。"""

from django.utils import timezone

from apps.accounts.models import Department, Level


def departments_in_scope(user):
    """經理以上可登記全部部門；組長、主任只能登記自己的部門；員工不能登記。"""
    if user.level >= Level.MANAGER:
        return Department.objects.order_by("name")
    if user.level >= Level.LEADER and user.department_id:
        return Department.objects.filter(pk=user.department_id)
    return Department.objects.none()


def can_register(user, employee):
    """經理以上可登記所有人員；組長、主任只能登記自己部門的人員；員工不能登記。"""
    if user.level >= Level.MANAGER:
        return True
    return user.level >= Level.LEADER and bool(user.department_id) and employee.department_id == user.department_id


def can_add(user, date):
    """今天：範圍內的人員任何有登記權的人都能新增紀錄；之前的日期要主任以上；不能登記未來日期。"""
    today = timezone.localdate()
    if date > today:
        return False
    return date == today or user.level >= Level.DIRECTOR


def can_void(user, event):
    """今天只能作廢自己登記的紀錄；之前的日期要主任以上（主任以上也可作廢別人登記的）。"""
    date = event.attendance.date
    if date > timezone.localdate() or event.voided_at:
        return False
    if user.level >= Level.DIRECTOR:
        return True
    return date == timezone.localdate() and event.created_by_id == user.pk


def station_departments(user):
    """工位安排的範圍：能不能進這頁由頁面權限決定；經理以上可安排全部部門，其他人只能安排自己的部門。"""
    if user.level >= Level.MANAGER:
        return Department.objects.order_by("name")
    if user.department_id:
        return Department.objects.filter(pk=user.department_id)
    return Department.objects.none()


def can_arrange(user, date):
    """工位不鎖定：當天隨時可改；之前的日期要主任以上；不能安排未來日期。"""
    today = timezone.localdate()
    if date > today:
        return False
    return date == today or user.level >= Level.DIRECTOR
