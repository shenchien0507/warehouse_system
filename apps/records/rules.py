"""登記紀錄的修改規則。門檻職級在後台「職級規則」設定（apps/accounts/levels.py 的 RULES）。"""

from apps.accounts.levels import allows

from .models import Record


def can_edit(user, record):
    """自己登記的紀錄可以修改、刪除；別人的依「登記紀錄：修改、刪除別人的紀錄」規則（預設主任以上）。"""
    return record.created_by_id == user.pk or allows(user, "records-edit-all")


def editable_records(user):
    """可以修改、刪除的紀錄（批量操作用）。"""
    if allows(user, "records-edit-all"):
        return Record.objects.all()
    return Record.objects.filter(created_by=user)


def linked_numbers(numbers):
    """這些編號裡，已經有撿貨或配貨登記的。有作業登記的紀錄不能刪、編號不能改，不然作業登記會對不到登記紀錄。"""
    from apps.worklog.models import WorkEntry

    return set(WorkEntry.objects.filter(number__in=list(numbers)).values_list("number", flat=True))


def is_linked(record):
    return bool(record.pk) and bool(linked_numbers([record.number]))


LINKED_NOTE = "已有撿貨或配貨登記"


def kind_names():
    """登記時可選的種類：今天當日統計有數字卡的種類（數字不是 0），沒有數字卡的不能選。"""
    from apps.tower.stats import kind_cards

    return [name for name, _, _ in kind_cards()[1]]


def registered_by_kind(day):
    """某天（登記日期）各種類登記的數量加總：{種類: 數量}，空白種類是未分類。"""
    totals = {}
    for kind, quantity in Record.objects.created_on(day).values_list("kind", "quantity"):
        totals[kind] = totals.get(kind, 0) + quantity
    return totals
