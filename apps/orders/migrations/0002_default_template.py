"""預設建立一個範本，對應目前電商後台匯出的「歷史紀錄」欄名。"""

from django.db import migrations

NAME = "電商後台歷史紀錄"
MAPPINGS = {
    "order_no": ("交易序號", True),
    "platform_order_no": ("平台訂單編號", False),
    "platform": ("交易平台", False),
    "shop": ("交易店鋪", False),
    "order_time": ("建立時間", False),
    "ship_time": ("出貨日期", False),
    "ship_type": ("出貨類型", False),
    "shipment_no": ("出貨單號", False),
    "product_code": ("商品編號", False),
    "product_name": ("商品名稱", False),
    "product_spec": ("商品樣式", False),
    "quantity": ("小計數量", True),
    "delivery_status": ("配送狀態", False),
}


def create(apps, schema_editor):
    ImportTemplate = apps.get_model("orders", "ImportTemplate")
    FieldMapping = apps.get_model("orders", "FieldMapping")
    template, created = ImportTemplate.objects.get_or_create(name=NAME, defaults={"note": "一列是一個商品，同一個交易序號是同一張訂單"})
    if created:
        FieldMapping.objects.bulk_create(
            FieldMapping(template=template, field=key, source_column=source, required=required)
            for key, (source, required) in MAPPINGS.items()
        )


def remove(apps, schema_editor):
    apps.get_model("orders", "ImportTemplate").objects.filter(name=NAME).delete()


class Migration(migrations.Migration):
    dependencies = [("orders", "0001_initial")]
    operations = [migrations.RunPython(create, remove)]
