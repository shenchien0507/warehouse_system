from django.db import migrations

# 作業登記的兩條職級規則預設主任（排序 30）以上；職級改過時取排序 30 以上最低的職級
CODES, DEFAULT_RANK = ["worklog-edit-all", "worklog-see-anomaly"], 30


def forwards(apps, schema_editor):
    Level = apps.get_model("accounts", "Level")
    LevelRule = apps.get_model("accounts", "LevelRule")
    level = Level.objects.filter(rank__gte=DEFAULT_RANK).order_by("rank").first()
    for code in CODES:
        LevelRule.objects.get_or_create(code=code, defaults={"min_level": level})


def backwards(apps, schema_editor):
    apps.get_model("accounts", "LevelRule").objects.filter(code__in=CODES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_level_rank_range"),
        ("worklog", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
