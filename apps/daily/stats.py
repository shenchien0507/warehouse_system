"""當日統計：計算規則和訂單統計一樣（orders.stats.summarize），只算沒重複的商品列。
- 當日累計：作業日全部批次，用當天第一批的統計分組版本，00:00:00 的訂單用各自那批的匯入時間判斷前後。
- 每一批：只算這批新出現的訂單；重複的另外列出。"""

from dataclasses import dataclass, field

from apps.orders.stats import LINE_VALUES, NO_TIME, summarize, version_groups

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

    @property
    def main(self):
        return self.rows if self.show_rows else self.total

    @property
    def shown(self):
        """卡片上切單前／後用的數字：和主要數字同一種（非去重或去重）。"""
        return self.row_counts if self.show_rows else self.counts

    @property
    def split(self):
        """[(key, 名稱, 數字, 寬度%)]：卡片上切單前／後的小長條，沒切時間的分組不畫。"""
        if not self.cutoff or not self.main:
            return []
        parts = [("before", f"{self.cutoff} 前"), ("after", f"{self.cutoff} 後"), ("no_time", "沒有下單時間")]
        return [(key, label, self.shown[key], self.shown[key] * 100 / self.main) for key, label in parts if self.shown.get(key)]


@dataclass
class Dashboard:
    total: int  # 當日訂單數（去重）
    groups: list  # GroupCard，依分組順序，沒有訂單的分組不列；未分組有訂單才列在最後
    batches: list  # [(批次, 之前累計, 這批新的, 之前累計寬度%, 這批寬度%)]


def segment_key(period):
    if period.endswith(" 前"):
        return "before"
    if period.endswith(" 後"):
        return "after"
    return "no_time" if period == NO_TIME else "all_day"


def dashboard(batches, summary, stat_groups):
    """當日累計的數字整理成 dashboard：每個分組一張數字卡（切單前／後）、批次累計。"""
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
    total = sum(b.new_order_count for b in batches)
    rows, running = [], 0
    for batch in batches:
        scale = total or 1
        rows.append((batch, running, batch.new_order_count, running * 100 / scale, batch.new_order_count * 100 / scale))
        running += batch.new_order_count
    return Dashboard(total=summary.total, groups=[c for c in cards.values() if c.total], batches=rows)
