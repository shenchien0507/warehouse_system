"""當日統計：計算規則和訂單統計一樣（orders.stats.summarize），只算沒重複的商品列。
- 當日累計：作業日全部批次，用當天第一批的統計分組版本，00:00:00 的訂單用各自那批的匯入時間判斷前後。
- 抽起的訂單（抽起中、或已轉到其他作業日）不算進當日累計和數字卡；每一批的表格照匯入時的樣子算。
- 每一批：只算這批新出現的訂單；重複的另外列出。
算好的結果暫存在記憶體（cache.py），資料沒變就不重算。"""

from dataclasses import dataclass, field

from django.db.models import Count, Max, Q

from apps.orders.stats import LINE_VALUES, NO_TIME, summarize, version_groups

from .cache import remember
from .models import DailyBatch, DailyHold, DailyLine, DailyOrder

DAY_VALUES = (*LINE_VALUES, "batch__imported_at")


def batch_key(batch):
    """一批的指紋：批次本身加上目前的商品列數、最大 id（之後手動放回的訂單會掛進最新一批，列數就變了）。"""
    return (batch.pk, batch.imported_at, batch.file_hash, batch.group_version_id, *batch.line_marks)


def mark_lines(batches):
    """每批記下目前的（商品列數, 最大 id），放在 batch.line_marks。"""
    marks = {
        batch_id: (count, last)
        for batch_id, count, last in DailyLine.objects.filter(batch__in=batches).order_by()
        .values("batch").annotate(count=Count("id"), last=Max("id")).values_list("batch", "count", "last")
    }
    for batch in batches:
        batch.line_marks = marks.get(batch.pk, (0, 0))


def day_key(batches):
    """作業日的指紋：全部批次，加上這天商品列的訂單有哪些抽單紀錄、各是什麼狀態（抽起、放回會改變當日累計）。"""
    holds = (
        DailyHold.objects.filter(order__lines__batch__in=batches).order_by("pk").values_list("pk", "status").distinct()
    )
    return (batches[0].work_date, tuple(batch_key(batch) for batch in batches), tuple(holds))


def day_stats(work_date):
    """回傳（批次 list, 當日累計統計）；那天沒有批次回傳 ([], None)。"""
    batches = list(DailyBatch.objects.filter(work_date=work_date).select_related("group_version", "mapping_version", "imported_by"))
    if not batches:
        return [], None
    mark_lines(batches)

    def compute():
        groups = version_groups(batches[0].group_version)
        lines = (
            DailyLine.objects.filter(batch__work_date=work_date, is_duplicate=False).exclude(order__holds__status__in=DailyHold.EXCLUDED)
            .values_list(*DAY_VALUES).iterator(chunk_size=5000)
        )
        return summarize(lines, batches[0].imported_at, groups, work_date).compact()

    return batches, remember(("day", day_key(batches)), compute)


def held_stats(batches, groups):
    """作業日抽起中的訂單，用和當日累計一樣的規則歸組（數字卡上的「抽起 N」）。batches 要是 day_stats 回傳的。"""
    work_date = batches[0].work_date

    def compute():
        lines = DailyLine.objects.filter(batch__work_date=work_date, is_duplicate=False, order__holds__status=DailyHold.HELD)
        return summarize(lines.values_list(*DAY_VALUES).iterator(chunk_size=5000), batches[0].imported_at, groups, work_date).compact()

    return remember(("held", day_key(batches)), compute)


def order_place(order, groups):
    """（分組名稱, 時段）：這張訂單在當日累計算在哪裡，例如（蝦皮隔日到貨, 14:00 前）。"""
    lines = DailyLine.objects.filter(order=order, is_duplicate=False).values_list(*DAY_VALUES)
    rows = summarize(lines, order.batch.imported_at, groups, order.work_date).groups
    return (rows[0].name, rows[0].period) if rows else ("", "")


def search_orders(work_date, keyword, limit=50):
    """作業日裡訂單號、平台訂單編號或出貨單號含有關鍵字的訂單（部分符合），回傳（訂單 list, 是否超過 limit）。"""
    keyword = keyword.strip()
    if not keyword:
        return [], False
    match = DailyLine.objects.filter(order__work_date=work_date).filter(
        Q(order_no__icontains=keyword) | Q(platform_order_no__icontains=keyword) | Q(shipment_no__icontains=keyword)
    )
    orders = list(
        DailyOrder.objects.filter(pk__in=match.values("order_id")).select_related("batch")
        .prefetch_related("holds__held_by", "holds__released_by", "holds__released_batch")
        .order_by("batch__seq", "order_no")[: limit + 1]
    )
    return orders[:limit], len(orders) > limit


def other_days(keyword, work_date):
    """其他作業日訂單號完全符合的訂單（這天查不到時提示在哪天）。"""
    return list(DailyOrder.objects.filter(order_no=keyword.strip()).exclude(work_date=work_date).select_related("batch"))


def batch_stats(batch, groups):
    """一批新出現的訂單的統計。batch 要是 day_stats 回傳的（帶著 line_marks）。"""

    def compute():
        lines = batch.lines.filter(is_duplicate=False).values_list(*LINE_VALUES).iterator(chunk_size=5000)
        return summarize(lines, batch.imported_at, groups, batch.work_date).compact()

    return remember(("batch", batch_key(batch)), compute)


def duplicates(work_date):
    """[(訂單號, 第一次出現在哪裡, [這天重複出現的批次序號])]，依第一次出現的作業日、批次、訂單號排。
    第一次出現在同一天寫「第 N 批」，在其他作業日寫「08/16 第 N 批」。"""
    seen = {}
    rows = (
        DailyLine.objects.filter(batch__work_date=work_date, is_duplicate=True)
        .values_list("order__order_no", "order__work_date", "order__batch__seq", "batch__seq").distinct()
    )
    for order_no, first_date, first_seq, again in rows:
        seen.setdefault((first_date, first_seq, order_no), set()).add(again)
    return [
        (order_no, f"第 {seq} 批" if day == work_date else f"{day:%m/%d} 第 {seq} 批", sorted(again))
        for (day, seq, order_no), again in sorted(seen.items())
    ]


@dataclass
class GroupCard:
    """dashboard 上一個分組的數字卡。"""

    name: str
    counts: dict  # 區段 key（before、after、all_day、no_time）→ 訂單數（去重）
    row_counts: dict = field(default_factory=dict)  # 同上，非去重（列數）
    total: int = 0
    rows: int = 0  # 非去重
    show_rows: bool = False  # 分組勾選「另外列出非去重」：卡片主要顯示非去重，去重放小字
    cutoff: str = ""  # 切單時間文字，例如 14:00；沒切時間空白
    registered: int = 0  # 登記紀錄裡這個種類今天（作業日）登記的數量（對帳用）
    carry: object = None  # 昨日未完成（closing.carry.CarryRow）：前日轉來的待印、待撿、待包，和目前還剩
    held: int = 0  # 抽起中的訂單（和主要數字同一種：非去重或去重），不算在上面的數字裡

    @property
    def main(self):
        return self.rows if self.show_rows else self.total

    @property
    def limit(self):
        """今天可以登記的總數：今天匯入的 + 前日待印（前日轉來還沒印的，今天要登記）。"""
        return self.main + (self.carry.unprinted if self.carry else 0)

    @property
    def register_state(self):
        """登記對總數：不足 short、剛好 even、超過 over。"""
        return "even" if self.registered == self.limit else "over" if self.registered > self.limit else "short"

    @property
    def over_by(self):
        return self.registered - self.limit

    @property
    def shown(self):
        """卡片上切單前／後用的數字：和主要數字同一種（非去重或去重）。"""
        return self.row_counts if self.show_rows else self.counts

    @property
    def split(self):
        """[(key, 名稱, 數字, 寬度%)]：卡片上當日的長條，切單前／後（沒切時間是一整段不分時段）。"""
        if self.cutoff:
            parts = [("before", f"{self.cutoff} 前"), ("after", f"{self.cutoff} 後"), ("no_time", "沒有下單時間")]
            rows = [(key, label, self.shown[key]) for key, label in parts if self.shown.get(key)]
        else:
            rows = [("all_day", "不分時段", self.main)] if self.main else []
        scale = sum(count for _, _, count in rows) or 1
        return [(key, label, count, count * 100 / scale) for key, label, count in rows]

    @property
    def carry_done(self):
        """昨日轉來的今天已經出掉幾張（看歷史日期沒有「目前還剩」時是 None）。"""
        if not self.carry or self.carry.left is None:
            return None
        return max(self.carry.total - self.carry.left, 0)

    @property
    def carry_done_width(self):
        """昨日長條黃色填滿的寬度%：已出 / 昨日轉來；沒有還剩的數字時整條填滿。"""
        if not self.carry or not self.carry.total:
            return 0
        done = self.carry_done
        return 100 if done is None else done * 100 / self.carry.total


@dataclass
class Dashboard:
    total: int  # 當日訂單數（去重）
    groups: list  # GroupCard，依分組順序，沒有訂單的分組不列；未分組有訂單才列在最後
    batches: list  # [(批次, 之前累計, 這批新的, 之前累計寬度%, 這批寬度%)]
    held: int = 0  # 抽起中的訂單數（去重）


def segment_key(period):
    if period.endswith(" 前"):
        return "before"
    if period.endswith(" 後"):
        return "after"
    return "no_time" if period == NO_TIME else "all_day"


def dashboard(batches, summary, stat_groups, registered=None, held=None, carry=None):
    """當日累計的數字整理成 dashboard：每個分組一張數字卡（切單前／後）、批次累計。
    registered：{種類: 登記數量}，卡片上顯示「已登記 / 總數」。held：抽起中訂單的統計（held_stats），卡片上顯示「抽起 N」。
    carry：昨日未完成（closing.carry.CarryReport），有轉過來的分組卡片標「昨日 N・剩 M」。"""
    cards = {
        g.name: GroupCard(g.name, {}, show_rows=g.show_rows, cutoff=g.cutoff.strftime("%H:%M") if g.cutoff else "")
        for g in stat_groups
    }
    for row in summary.groups:  # 主表：每張訂單只在一列，同分組各列相加就是分組總數
        card = cards.setdefault(row.name, GroupCard(row.name, {}))
        key = segment_key(row.period)
        card.counts[key] = card.counts.get(key, 0) + row.count.distinct
        card.total += row.count.distinct
        card.row_counts[key] = card.row_counts.get(key, 0) + row.count.rows
        card.rows += row.count.rows
    for row in held.groups if held else []:
        card = cards.setdefault(row.name, GroupCard(row.name, {}))
        card.held += row.count.rows if card.show_rows else row.count.distinct
    for name, quantity in (registered or {}).items():
        if name in cards:
            cards[name].registered = quantity
    for name, row in (carry.by_name() if carry else {}).items():
        if name in cards:
            cards[name].carry = row
    total = sum(b.new_order_count for b in batches)
    rows, running = [], 0
    for batch in batches:
        scale = total or 1
        rows.append((batch, running, batch.new_order_count, running * 100 / scale, batch.new_order_count * 100 / scale))
        running += batch.new_order_count
    return Dashboard(
        total=summary.total, groups=[c for c in cards.values() if c.total or c.held], batches=rows, held=held.total if held else 0
    )
