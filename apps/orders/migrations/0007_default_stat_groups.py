"""預設統計分組 v1 並生效：重現分組功能上線前寫死的規則，數字跟之前一樣。之前匯入的批次都算 v1。"""

import datetime

from django.db import migrations
from django.utils import timezone

GROUPS = [
    ("蝦皮無包裝", 10, True, True, {"platforms": ["蝦皮購物"], "ship_types": ["蝦皮無包裝", "蝦皮無包裝[代收]"]}),
    ("蝦皮隔日到貨", 20, True, False, {"platforms": ["蝦皮購物"], "ship_types": ["蝦皮隔日到貨", "蝦皮隔日到貨[代收]"]}),
    ("蝦皮其他", 30, False, False, {"platforms": ["蝦皮購物"]}),
    ("其他平台", 40, True, False, {}),
]


def create(apps, schema_editor):
    GroupVersion = apps.get_model("orders", "GroupVersion")
    StatGroup = apps.get_model("orders", "StatGroup")
    StatCondition = apps.get_model("orders", "StatCondition")
    ImportBatch = apps.get_model("orders", "ImportBatch")
    if GroupVersion.objects.exists():
        return
    version = GroupVersion.objects.create(
        number=1, note="預設：蝦皮無包裝、蝦皮隔日到貨分 14:00 前後，其他平台分 14:00 前後", is_active=True, activated_at=timezone.now(),
    )
    for name, order, split, show_rows, condition in GROUPS:
        group = StatGroup.objects.create(
            version=version, name=name, sort_order=order, cutoff=datetime.time(14, 0) if split else None,
            midnight_uses_import_time=split, show_rows=show_rows,
        )
        StatCondition.objects.create(group=group, **condition)
    ImportBatch.objects.filter(group_version__isnull=True).update(group_version=version)


class Migration(migrations.Migration):
    dependencies = [("orders", "0006_stat_groups")]
    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
