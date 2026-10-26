"""匯入訂單：用目前生效的欄位對應版本讀整份檔，有任何一列錯誤就整份不匯入。"""

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from . import stats
from .importer import read_lines
from .models import ImportBatch, MappingVersion, OrderLine

TEXT_FIELDS = [f.name for f in OrderLine._meta.get_fields() if f.get_internal_type() == "CharField"]


@dataclass
class ImportOutcome:
    batch: ImportBatch = None
    message: str = ""  # 整份不能讀時的原因
    errors: list = field(default_factory=list)  # [(第幾列, 欄位名稱, 原始值, 錯誤)]
    error_count: int = 0


def aware(value):
    return timezone.make_aware(value) if value is not None and timezone.is_naive(value) else value


def to_line(batch, row_no, values):
    data = {key: values[key] for key in values}
    for key in TEXT_FIELDS:
        if key in data:
            data[key] = (data[key] or "")[: OrderLine._meta.get_field(key).max_length]
    data["order_time"], data["ship_time"] = aware(data["order_time"]), aware(data["ship_time"])
    return OrderLine(batch=batch, row_no=row_no, **data)


def import_file(user, uploaded):
    version = MappingVersion.active()
    if version is None:
        return ImportOutcome(message="目前沒有生效的欄位對應版本，請先到後台「匯入欄位對應」設定。")
    result = read_lines(version, uploaded, validate=stats.validate)
    if result.missing_must_map:
        names = "、".join(f"{c.field.label}（「{c.source_column}」）" for c in result.missing_must_map)
        return ImportOutcome(message=f"檔案裡找不到 {names} 這一欄，整份沒有匯入。來源檔欄名改了的話，請到後台新增欄位對應版本。")
    if result.error_count:
        return ImportOutcome(
            message=f"有 {result.error_count} 列資料有問題，整份沒有匯入。請改好後重新匯入。",
            errors=result.errors, error_count=result.error_count,
        )
    if not result.lines:
        return ImportOutcome(message="檔案裡沒有資料列，沒有匯入。")
    with transaction.atomic():
        batch = ImportBatch.objects.create(
            file_name=uploaded.name[:200], imported_by=user, mapping_version=version,
            line_count=len(result.lines), order_count=len({values["order_no"] for _, values in result.lines}),
        )
        OrderLine.objects.bulk_create((to_line(batch, row_no, values) for row_no, values in result.lines), batch_size=2000)
    return ImportOutcome(batch=batch)
