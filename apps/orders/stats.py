"""訂單統計：每匯入一份檔案就是一批，一批獨立計算，數的都是訂單數（看訂單號）。

- 去重：同一個訂單號只算 1。非去重：有幾列就算幾張（分組勾選「另外列出非去重」才顯示）。
- 先依下單日期分開，每一天各自歸組、分前後；沒有下單時間的另列「沒有日期」。
- 訂單依後台「統計分組」的條件歸組，符合多組時算進排最前面的那組；都不符合的列在「未分組」。
- 分組有切開時間時，依下單時間分成前、後兩個數字；只看到分鐘，切開時間整分（含 59 秒）算前。
  分組勾選「下單時間是 00:00:00 時用匯入時間」時，這種只有日期的訂單改用這批的匯入時間判斷。
分組有版本：每個批次用匯入當下生效的分組版本計算，之後改分組不影響舊批次。"""

from dataclasses import dataclass, field
from datetime import date, time

from django.utils import timezone


UNGROUPED = "未分組"
NO_TIME = "沒有下單時間"


def local(value):
    return timezone.localtime(value) if timezone.is_aware(value) else value


def date_only(order_time):
    """下單時間只有日期（00:00:00）。"""
    return local(order_time).time() == time(0, 0)


def labels(cutoff):
    text = cutoff.strftime("%H:%M")
    return f"{text} 前", f"{text} 後"


def cutoff_period(cutoff, moment):
    moment = local(moment)
    before, after = labels(cutoff)
    return before if (moment.hour, moment.minute) <= (cutoff.hour, cutoff.minute) else after


def period(group, order_time, imported_at):
    """這筆訂單在分組裡算哪個時段；不分時段回傳空字串。"""
    if group is None or group.cutoff is None:
        return ""
    if order_time is None:
        return NO_TIME
    if group.midnight_uses_import_time and date_only(order_time):
        return cutoff_period(group.cutoff, imported_at)
    return cutoff_period(group.cutoff, order_time)


def find_group(groups, platform, shop, ship_type):
    for group in groups:
        if any(c.matches(platform, shop, ship_type) for c in group.conditions.all()):
            return group
    return None


@dataclass
class Count:
    orders: set = field(default_factory=set)
    rows: int = 0

    def add(self, order_no):
        self.orders.add(order_no)
        self.rows += 1

    @property
    def distinct(self):
        return len(self.orders)


def order_date(order_time):
    return local(order_time).date() if order_time is not None else None


@dataclass
class GroupRow:
    date: object  # 下單日期；None = 沒有下單時間
    name: str
    period: str
    show_rows: bool
    count: Count = field(default_factory=Count)


@dataclass
class DetailRow:
    date: object
    group: str
    platform: str
    shop: str
    ship_type: str
    period: str
    show_rows: bool
    count: Count = field(default_factory=Count)


@dataclass
class Summary:
    groups: list  # GroupRow，依日期、分組順序；0 張的不列
    details: list  # DetailRow：日期 × 分組 × 平台 × 店鋪 × 出貨類型 × 時段，供核對
    days: dict  # 日期 → 當天訂單數（去重），依日期排
    by_import_time: set  # 改用匯入時間判斷前後的訂單號
    total: int  # 全部訂單數（去重）

    @property
    def by_day(self):
        """[(日期, 當天訂單數, 當天的 GroupRow)]，給頁面一天一段顯示。"""
        return [(day, count, [r for r in self.groups if r.date == day]) for day, count in self.days.items()]


def summarize(lines, imported_at, groups):
    """lines：[(平台, 店鋪, 出貨類型, 下單時間, 訂單號)]；groups：依順序排好的 StatGroup（含 conditions）。"""
    groups = list(groups)
    table = {}
    details = {}
    by_import_time, everyone, per_day = set(), set(), {}
    for platform, shop, ship_type, order_time, order_no in lines:
        platform, shop, ship_type = platform or "", shop or "", ship_type or ""
        group = find_group(groups, platform, shop, ship_type)
        name = group.name if group else UNGROUPED
        show_rows = group.show_rows if group else False
        p = period(group, order_time, imported_at)
        day = order_date(order_time)
        if group and group.cutoff and group.midnight_uses_import_time and order_time is not None and date_only(order_time):
            by_import_time.add(order_no)
        row = table.get((day, name, p))
        if row is None:
            row = table[(day, name, p)] = GroupRow(day, name, p, show_rows)
        row.count.add(order_no)
        key = (day, name, platform, shop, ship_type, p)
        detail = details.get(key)
        if detail is None:
            detail = details[key] = DetailRow(*key, show_rows)
        detail.count.add(order_no)
        everyone.add(order_no)
        per_day.setdefault(day, set()).add(order_no)
    order = {g.name: i for i, g in enumerate(groups)}
    rank = lambda name: order.get(name, len(order))  # 未分組排最後
    by_day = lambda day: (day is None, day or date.min)  # 沒有日期排最後
    return Summary(
        groups=sorted(table.values(), key=lambda r: (by_day(r.date), rank(r.name), r.period == NO_TIME, r.period)),
        details=sorted(details.values(), key=lambda r: (by_day(r.date), rank(r.group), r.platform, r.shop, r.ship_type, r.period)),
        days={day: len(per_day[day]) for day in sorted(per_day, key=by_day)},
        by_import_time=by_import_time,
        total=len(everyone),
    )


def batch_stats(batch):
    lines = batch.lines.values_list("platform", "shop", "ship_type", "order_time", "order_no").iterator(chunk_size=5000)
    groups = batch.group_version.groups.prefetch_related("conditions") if batch.group_version else []
    return summarize(lines, batch.imported_at, groups)


def validate(values):
    """匯入時每列的檢查，回傳 [(系統欄位 key, 錯誤)]。時間怎麼分由分組決定，匯入只要求訂單號。"""
    return [("order_no", "訂單號空白")] if not values["order_no"] else []
