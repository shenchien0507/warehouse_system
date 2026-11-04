"""匯入訂單：一次可放多個分類的檔案，用目前生效的欄位對應版本讀；任何一份有錯就整次不匯入。"""

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from . import stats
from .importer import ImportFileError, read_lines
from .models import GroupVersion, ImportBatch, MappingVersion, OrderLine, StatRun

TEXT_FIELDS = [f.name for f in OrderLine._meta.get_fields() if f.get_internal_type() == "CharField"]


@dataclass
class ImportOutcome:
    """一份檔案讀完的結果；message 空白代表沒問題。"""

    message: str = ""  # 整份不能匯入的原因
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


def check_versions():
    """回傳（欄位對應版本, 統計分組版本, 錯誤訊息）。"""
    version, group_version = MappingVersion.active(), GroupVersion.active()
    if version is None:
        return None, None, "目前沒有生效的欄位對應版本，請先到後台「匯入欄位對應」設定。"
    if group_version is None:
        return None, None, "目前沒有生效的統計分組版本，請先到後台「統計分組」設定。"
    return version, group_version, ""


def read_file(version, uploaded):
    """讀一份檔案：回傳 (ReadResult, ImportOutcome)；檔案有問題時 outcome 帶原因。"""
    try:
        result = read_lines(version, uploaded, validate=stats.validate)
    except ImportFileError as exc:
        return None, ImportOutcome(message=str(exc))
    if result.missing_must_map:
        names = "、".join(f"{c.field.label}（「{c.source_column}」）" for c in result.missing_must_map)
        return result, ImportOutcome(message=f"檔案裡找不到 {names} 這一欄。來源檔欄名改了的話，請到後台新增欄位對應版本。")
    if result.error_count:
        return result, ImportOutcome(
            message=f"有 {result.error_count} 列資料有問題，請改好後重新匯入。", errors=result.errors, error_count=result.error_count,
        )
    if not result.lines:
        return result, ImportOutcome(message="檔案裡沒有資料列。")
    return result, ImportOutcome()


def create_batch(run, category, uploaded, result, version, group_version):
    batch = ImportBatch.objects.create(
        run=run, category=category, category_name=category.name if category else "",
        file_name=uploaded.name[:200], work_date=run.work_date, imported_by=run.created_by,
        mapping_version=version, group_version=group_version,
        line_count=len(result.lines), order_count=len({values["order_no"] for _, values in result.lines}),
    )
    OrderLine.objects.bulk_create((to_line(batch, row_no, values) for row_no, values in result.lines), batch_size=2000)
    return batch


@dataclass
class RunOutcome:
    run: StatRun = None
    message: str = ""  # 整次不能匯入的原因（例如沒有生效版本）
    files: list = field(default_factory=list)  # [(分類, ImportOutcome)]，有問題的檔案


def import_run(user, work_date, files):
    """一次匯入多個分類的檔案：files = [(ImportCategory, 上傳檔)]。任何一份有問題就全部不匯入。"""
    version, group_version, message = check_versions()
    if message:
        return RunOutcome(message=message)
    results, problems = [], []
    for category, uploaded in files:
        result, outcome = read_file(version, uploaded)
        if outcome.message:
            problems.append((category, outcome))
        results.append((category, uploaded, result))
    if problems:
        return RunOutcome(message="有檔案有問題，這次全部沒有匯入。", files=problems)
    with transaction.atomic():
        run = StatRun.objects.create(work_date=work_date or timezone.localdate(), created_by=user)
        for category, uploaded, result in results:
            create_batch(run, category, uploaded, result, version, group_version)
    return RunOutcome(run=run)
