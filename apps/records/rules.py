"""登記紀錄的修改規則。門檻職級在後台「職級規則」設定（apps/accounts/levels.py 的 RULES）。"""

from apps.accounts.levels import allows


def can_edit(user, record):
    """自己登記的紀錄可以修改、刪除；別人的依「登記紀錄：修改、刪除別人的紀錄」規則（預設主任以上）。"""
    return record.created_by_id == user.pk or allows(user, "records-edit-all")
