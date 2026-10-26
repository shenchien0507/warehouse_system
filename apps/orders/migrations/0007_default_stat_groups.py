"""預設統計分組：重現分組功能上線前寫死的規則，數字跟之前一樣。"""

import datetime

from django.db import migrations

GROUPS = [
    ("蝦皮無包裝", 10, True, True, {"platforms": ["蝦皮購物"], "ship_types": ["蝦皮無包裝", "蝦皮無包裝[代收]"]}),
    ("蝦皮隔日到貨", 20, True, False, {"platforms": ["蝦皮購物"], "ship_types": ["蝦皮隔日到貨", "蝦皮隔日到貨[代收]"]}),
    ("蝦皮其他", 30, False, False, {"platforms": ["蝦皮購物"]}),
    ("其他平台", 40, True, False, {}),
]


def create(apps, schema_editor):
    StatGroup = apps.get_model("orders", "StatGroup")
    StatCondition = apps.get_model("orders", "StatCondition")
    if StatGroup.objects.exists():
        return
    for name, order, split, show_rows, condition in GROUPS:
        group = StatGroup.objects.create(
            name=name, sort_order=order, cutoff=datetime.time(14, 0) if split else None,
            midnight_uses_import_time=split, show_rows=show_rows,
        )
        StatCondition.objects.create(group=group, **condition)


class Migration(migrations.Migration):
    dependencies = [("orders", "0006_stat_groups")]
    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
