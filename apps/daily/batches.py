"""匯入一批到當日資料池：用目前生效的欄位對應、統計分組版本（和訂單統計共用）；有錯整份不匯入。
一張訂單只屬於一個作業日（當天出完，不留到隔天）：比對重複時看全部作業日。
避免重複匯入製造垃圾資料：任何一天匯入過內容一樣的檔案、或檔案裡的訂單全部都已匯入過（抽起中的除外），整份擋掉。
抽起中的訂單又出現在檔案裡：同一作業日自動放回（這次的列照樣標重複）；其他作業日就轉到這天，算進這天的新訂單。"""

import hashlib
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.orders.batches import ImportOutcome, aware, check_versions, read_file

from .models import DailyBatch, DailyHold, DailyLine, DailyOrder

TEXT_FIELDS = [f.name for f in DailyLine._meta.get_fields() if f.get_internal_type() == "CharField"]


@dataclass
class BatchOutcome:
    batch: DailyBatch = None
    message: str = ""
    file: ImportOutcome = field(default_factory=ImportOutcome)  # 檔案的問題（列錯誤）


def to_line(batch, order, row_no, values, is_duplicate):
    data = dict(values)
    for key in TEXT_FIELDS:
        if key in data:
            data[key] = (data[key] or "")[: DailyLine._meta.get_field(key).max_length]
    data["order_time"], data["ship_time"] = aware(data["order_time"]), aware(data["ship_time"])
    return DailyLine(batch=batch, order=order, row_no=row_no, is_duplicate=is_duplicate, **data)


def file_hash(uploaded):
    digest = hashlib.sha256()
    for chunk in uploaded.chunks():
        digest.update(chunk)
    uploaded.seek(0)
    return digest.hexdigest()


def known_orders(order_nos):
    """{訂單號: DailyOrder}，已匯入過的訂單；以前同一張出現在幾天的，取最早那天。已轉到其他作業日的不算（看轉過去的那筆）。"""
    orders = (
        DailyOrder.objects.filter(order_no__in=order_nos).exclude(holds__status=DailyHold.MOVED)
        .order_by("-work_date", "-batch__seq")
    )
    return {o.order_no: o for o in orders}


def held_orders(orders):
    """{訂單號: 抽起中的 DailyHold}。"""
    holds = DailyHold.objects.filter(order__in=list(orders.values()), status=DailyHold.HELD).select_related("order")
    return {h.order.order_no: h for h in holds}


def split_known(order_nos, work_date):
    """（已匯入過、這次算重複的 {訂單號: DailyOrder}, 抽起中的 {訂單號: DailyHold}）。
    抽起中、但屬於其他作業日的訂單不算重複：轉到這天當新訂單。"""
    existing = known_orders(order_nos)
    holds = held_orders(existing)
    moving = {no for no, hold in holds.items() if hold.order.work_date != work_date}
    return {no: o for no, o in existing.items() if no not in moving}, holds


def import_batch(user, work_date, uploaded):
    """匯入一份檔案成為作業日的下一批。已在之前批次（含其他作業日）出現的訂單照存但標記重複，不算進當日統計。"""
    version, group_version, message = check_versions()
    if message:
        return BatchOutcome(message=message)
    work_date = work_date or timezone.localdate()
    fingerprint = file_hash(uploaded)
    same = DailyBatch.objects.filter(file_hash=fingerprint).first()
    if same:
        return BatchOutcome(message=f"這份檔案和{same}（{same.file_name}）內容一樣，已經匯入過，這次沒有匯入。")
    result, outcome = read_file(version, uploaded)
    if outcome.message:
        return BatchOutcome(message=outcome.message, file=outcome)
    max_length = DailyOrder._meta.get_field("order_no").max_length
    order_nos = list(dict.fromkeys(values["order_no"][:max_length] for _, values in result.lines))
    existing, holds = split_known(order_nos, work_date)
    if len(existing) == len(order_nos) and not holds:
        return BatchOutcome(message=f"檔案裡的 {len(order_nos)} 張訂單全部都已在之前的批次匯入過，沒有新訂單，這次沒有匯入。")
    with transaction.atomic():
        last = DailyBatch.objects.filter(work_date=work_date).aggregate(seq=Max("seq"))["seq"]
        batch = DailyBatch.objects.create(
            work_date=work_date, seq=(last or 0) + 1, file_name=uploaded.name[:200], file_hash=fingerprint, imported_by=user,
            mapping_version=version, group_version=group_version, line_count=len(result.lines), order_count=len(order_nos),
        )
        existing, holds = split_known(order_nos, work_date)
        new_orders = DailyOrder.objects.bulk_create(
            DailyOrder(work_date=work_date, order_no=no, batch=batch) for no in order_nos if no not in existing
        )
        if new_orders and new_orders[0].pk is None:  # MySQL 的 bulk_create 不回傳 pk，重新查一次
            new_orders = DailyOrder.objects.filter(batch=batch)
        orders = {**existing, **{o.order_no: o for o in new_orders}}
        DailyLine.objects.bulk_create(
            (
                to_line(batch, orders[values["order_no"][:max_length]], row_no, values, values["order_no"][:max_length] in existing)
                for row_no, values in result.lines
            ),
            batch_size=2000,
        )
        batch.new_order_count = len(order_nos) - len(existing)
        batch.save(update_fields=["new_order_count"])
        for no, hold in holds.items():
            hold.close(DailyHold.RETURNED if no in existing else DailyHold.MOVED, user, batch)
    return BatchOutcome(batch=batch)
