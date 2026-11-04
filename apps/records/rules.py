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


def over_total_errors(new_rows=(), edited=()):
    """登記後會超過當日統計總數的種類，回傳錯誤訊息（空的就是可以存）。
    new_rows 是新登記的 [(種類, 數量)]；edited 是改好但還沒存的紀錄（修改、批量修改），先扣掉它們原本的數量再算，
    不是今天登記的紀錄不算進今天的已登記，略過。
    已經超出的種類，只要這次沒有讓它更多就放行（例如把數量改小）；當日統計沒有的種類（未分類）不檢查。
    有新訂單要先到當日統計匯入，總數才會增加，不能直接登記上去。"""
    from apps.tower.stats import kind_cards

    day, cards = kind_cards()
    totals = {name: total for name, _, total in cards}
    before = registered_by_kind(day)
    after = dict(before)
    rows = list(new_rows)
    originals = Record.objects.created_on(day).filter(pk__in=[r.pk for r in edited if r.pk]).in_bulk()
    for record in edited:
        original = originals.get(record.pk)
        if original is not None:
            after[original.kind] = after.get(original.kind, 0) - original.quantity
            rows.append((record.kind, record.quantity))
    for kind, quantity in rows:
        after[kind] = after.get(kind, 0) + quantity
    errors = []
    for kind in dict.fromkeys(kind for kind, _ in rows):
        count = after.get(kind, 0)
        if kind in totals and count > totals[kind] and count > before.get(kind, 0):
            errors.append(
                f"「{kind}」當日統計總數 {totals[kind]}，這樣登記會變成 {count}，多了 {count - totals[kind]}，不能存。"
                "有新訂單請先到當日統計匯入，總數增加後再登記。"
            )
    return errors
