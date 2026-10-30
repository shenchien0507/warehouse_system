from django.db import migrations

# 「登記紀錄：修改、刪除別人登記的紀錄」預設主任（排序 30）以上；職級改過時取排序 30 以上最低的職級
CODE, DEFAULT_RANK = "records-edit-all", 30


def forwards(apps, schema_editor):
    Level = apps.get_model("accounts", "Level")
    LevelRule = apps.get_model("accounts", "LevelRule")
    level = Level.objects.filter(rank__gte=DEFAULT_RANK).order_by("rank").first()
    LevelRule.objects.get_or_create(code=CODE, defaults={"min_level": level})


def backwards(apps, schema_editor):
    apps.get_model("accounts", "LevelRule").objects.filter(code=CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_level_rank_range"),
        ("records", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
