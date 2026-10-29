"""當日統計：計算規則和訂單統計一樣（orders.stats.summarize），只算沒重複的商品列。
- 當日累計：作業日全部批次，用當天第一批的統計分組版本，00:00:00 的訂單用各自那批的匯入時間判斷前後。
- 每一批：只算這批新出現的訂單；重複的另外列出。"""

from dataclasses import dataclass

from apps.orders.stats import LINE_VALUES, NO_TIME, UNGROUPED, summarize, version_groups

from .models import DailyBatch, DailyLine

DAY_VALUES = (*LINE_VALUES, "batch__imported_at")


def day_stats(work_date):
    """回傳（批次 list, 當日累計統計）；那天沒有批次回傳 ([], None)。"""
    batches = list(DailyBatch.objects.filter(work_date=work_date).select_related("group_version", "mapping_version", "imported_by"))
    if not batches:
        return [], None
    groups = version_groups(batches[0].group_version)
    lines = DailyLine.objects.filter(batch__work_date=work_date, is_duplicate=False).values_list(*DAY_VALUES).iterator(chunk_size=5000)
    return batches, summarize(lines, batches[0].imported_at, groups, work_date)


def batch_stats(batch, groups):
    """一批新出現的訂單的統計。"""
    lines = batch.lines.filter(is_duplicate=False).values_list(*LINE_VALUES).iterator(chunk_size=5000)
    return summarize(lines, batch.imported_at, groups, batch.work_date)


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


SEGMENTS = [("before", "切單前"), ("after", "切單後"), ("all_day", "不分時段"), ("no_time", "沒有下單時間")]


@dataclass
class GroupBar:
    name: str
    counts: dict  # 區段 key → 訂單數（去重）
    total: int = 0

    def segments(self, scale):
        """[(key, 名稱, 數字, 寬度%)]，只列有數字的區段；scale 是最長那條的總數。"""
        return [(key, label, self.counts[key], self.counts[key] * 100 / scale) for key, label in SEGMENTS if self.counts.get(key)]


@dataclass
class Dashboard:
    total: int  # 當日訂單數（去重）
    before: int
    after: int
    groups: list  # GroupBar，依分組順序，未分組最後
    batches: list  # [(批次, 之前累計, 這批新的, 之前累計寬度%, 這批寬度%)]
    max_group: int = 1

    @property
    def group_rows(self):
        return [(bar, bar.segments(self.max_group)) for bar in self.groups]


def segment_key(period):
    if period.endswith(" 前"):
        return "before"
    if period.endswith(" 後"):
        return "after"
    return "no_time" if period == NO_TIME else "all_day"


def dashboard(batches, summary, stat_groups):
    """當日累計的數字整理成 dashboard：上排數字、各分組長條（切單前／後）、批次累計。"""
    bars = {}
    for row in summary.groups:  # 主表：每張訂單只在一列，同分組各列相加就是分組總數
        bar = bars.setdefault(row.name, GroupBar(row.name, {}))
        key = segment_key(row.period)
        bar.counts[key] = bar.counts.get(key, 0) + row.count.distinct
        bar.total += row.count.distinct
    groups = list(bars.values())
    order = {g.name: i for i, g in enumerate(stat_groups)}
    groups.sort(key=lambda b: (b.name == UNGROUPED, order.get(b.name, len(order))))
    total = sum(b.new_order_count for b in batches)
    rows, running = [], 0
    for batch in batches:
        scale = total or 1
        rows.append((batch, running, batch.new_order_count, running * 100 / scale, batch.new_order_count * 100 / scale))
        running += batch.new_order_count
    return Dashboard(
        total=summary.total,
        before=sum(b.counts.get("before", 0) for b in groups),
        after=sum(b.counts.get("after", 0) for b in groups),
        groups=groups,
        batches=rows,
        max_group=max((b.total for b in groups), default=0) or 1,
    )
