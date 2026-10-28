"""當日統計：計算規則和訂單統計一樣（orders.stats.summarize），只算沒重複的商品列。
- 當日累計：作業日全部批次，用當天第一批的統計分組版本，00:00:00 的訂單用各自那批的匯入時間判斷前後。
- 每一批：只算這批新出現的訂單；重複的另外列出。"""

from apps.orders.stats import LINE_VALUES, summarize, version_groups

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
