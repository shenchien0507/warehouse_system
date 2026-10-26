"""訂單統計：每匯入一份檔案就是一批，一批獨立計算，數的都是訂單數（看訂單號）。

- 去重：同一個訂單號只算 1。
- 非去重：有幾列就算幾張。只有 BOTH_COUNT_TYPES 的出貨方式要另外列出。
- 平台不在 NO_SPLIT_PLATFORMS 的訂單，依下單時間分成「14:00 前」「14:00 後」兩個數字；只看到分鐘，14:00 整（含 14:00:59）算前。
  下單時間是 00:00:00 的（例如 friDay 只給日期），改用這一批的匯入時間判斷。
分組之後再做；規則要改時改這裡的常數。"""

from dataclasses import dataclass, field
from datetime import time

from django.utils import timezone

NO_SPLIT_PLATFORMS = {"蝦皮購物"}
CUTOFF = time(14, 0)
BOTH_COUNT_TYPES = {"蝦皮無包裝"}
VARIANT_SUFFIXES = ["[代收]"]  # 「蝦皮無包裝[代收]」和「蝦皮無包裝」用同樣算法

BEFORE, AFTER = "14:00 前", "14:00 後"


def base_type(ship_type):
    for suffix in VARIANT_SUFFIXES:
        if ship_type.endswith(suffix):
            return ship_type[: -len(suffix)]
    return ship_type


def counts_rows(ship_type):
    """這個出貨方式要不要另外列出非去重的數字。"""
    return base_type(ship_type) in BOTH_COUNT_TYPES


def splits(platform):
    return platform not in NO_SPLIT_PLATFORMS


def local(value):
    return timezone.localtime(value) if timezone.is_aware(value) else value


def date_only(order_time):
    """下單時間只有日期（00:00:00）。"""
    return local(order_time).time() == time(0, 0)


def period(platform, order_time, imported_at=None):
    """不分時段回傳空字串；要分但沒有下單時間回傳 None（匯入時會擋下）。
    下單時間是 00:00:00 時改用匯入時間 imported_at。"""
    if not splits(platform):
        return ""
    if order_time is None:
        return None
    return cutoff_period(imported_at if imported_at is not None and date_only(order_time) else order_time)


def cutoff_period(moment):
    moment = local(moment)
    return BEFORE if (moment.hour, moment.minute) <= (CUTOFF.hour, CUTOFF.minute) else AFTER


def validate(values):
    """匯入時每列的檢查，回傳 [(系統欄位 key, 錯誤)]。"""
    errors = []
    if not values["order_no"]:
        errors.append(("order_no", "訂單號空白"))
    if splits(values["platform"] or "") and values["order_time"] is None:
        errors.append(("order_time", "不是蝦皮購物的訂單要有下單時間，才能分 14:00 前後"))
    return errors


@dataclass
class StatRow:
    platform: str
    ship_type: str
    period: str
    orders: set = field(default_factory=set)
    rows: int = 0

    @property
    def distinct(self):
        return len(self.orders)

    @property
    def show_rows(self):
        return counts_rows(self.ship_type)


@dataclass
class Summary:
    rows: list
    by_import_time: set  # 下單時間是 00:00:00、改用匯入時間判斷 14:00 前後的訂單號


def summarize(lines, imported_at=None):
    """lines：[(平台, 出貨方式, 下單時間, 訂單號)]；回傳 Summary，rows 依平台、出貨方式、時段排序。"""
    table = {}
    by_import_time = set()
    for platform, ship_type, order_time, order_no in lines:
        platform, ship_type = platform or "", ship_type or ""
        if splits(platform) and order_time is not None and date_only(order_time):
            by_import_time.add(order_no)
        key = (platform, ship_type, period(platform, order_time, imported_at) or "")
        row = table.get(key)
        if row is None:
            row = table[key] = StatRow(*key)
        row.orders.add(order_no)
        row.rows += 1
    rows = sorted(table.values(), key=lambda r: (r.platform not in NO_SPLIT_PLATFORMS, r.platform, r.ship_type, r.period))
    return Summary(rows, by_import_time)


def batch_stats(batch):
    lines = batch.lines.values_list("platform", "ship_type", "order_time", "order_no").iterator(chunk_size=5000)
    return summarize(lines, batch.imported_at)
