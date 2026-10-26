"""預設建立 v1 並生效，對應目前電商後台匯出的「歷史紀錄」欄名。"""

from django.db import migrations
from django.utils import timezone

SOURCE_COLUMNS = [
    "交易平台", "交易店鋪", "交易序號", "買家姓名", "出貨日期", "出貨類型", "商品編號", "商品名稱", "商品樣式",
    "小計數量", "建立時間", "會員交易筆數", "系統備註", "發票紀錄", "發票開立方式", "收件者姓名", "平台訂單編號",
    "出貨單號", "商品小計", "商品單價", "收件者手機", "收件者地址", "配送狀態", "配送狀態描述", "店家備註",
]
MAPPINGS = {
    "order_no": "交易序號",
    "platform_order_no": "平台訂單編號",
    "platform": "交易平台",
    "shop": "交易店鋪",
    "order_time": "建立時間",
    "ship_time": "出貨日期",
    "ship_type": "出貨類型",
    "shipment_no": "出貨單號",
    "product_code": "商品編號",
    "product_name": "商品名稱",
    "product_spec": "商品樣式",
    "quantity": "小計數量",
}


def create(apps, schema_editor):
    MappingVersion = apps.get_model("orders", "MappingVersion")
    ColumnMapping = apps.get_model("orders", "ColumnMapping")
    if MappingVersion.objects.exists():
        return
    version = MappingVersion.objects.create(
        number=1, source_file_name="歷史紀錄.xlsx", source_columns=SOURCE_COLUMNS,
        note="預設：電商後台歷史紀錄（一列是一個商品，同一個交易序號是同一張訂單）",
        is_active=True, activated_at=timezone.now(),
    )
    ColumnMapping.objects.bulk_create(
        ColumnMapping(version=version, field=key, source_column=source) for key, source in MAPPINGS.items()
    )


def remove(apps, schema_editor):
    apps.get_model("orders", "MappingVersion").objects.filter(number=1).delete()


class Migration(migrations.Migration):
    dependencies = [("orders", "0003_mapping_versions")]
    operations = [migrations.RunPython(create, remove)]
