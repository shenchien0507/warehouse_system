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


def can_edit(user, date, record=None):
    """當天的紀錄由登記人自己修改；之前的日期要主任以上才能新增或修改；不能登記未來日期。"""
    today = timezone.localdate()
    if date > today:
        return False
    if user.level >= Level.DIRECTOR:
        return True
    if date != today:
        return False
    return record is None or record.created_by_id == user.pk
