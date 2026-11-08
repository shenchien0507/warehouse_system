import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# 「日結」職級規則（按日結、取消日結）預設主任（排序 30）以上；職級改過時取排序 30 以上最低的職級。
# 頁面權限和其他功能一樣由管理員在後台「頁面權限」開放。
CODE, DEFAULT_RANK = "day-close", 30


def forwards(apps, schema_editor):
    Level = apps.get_model("accounts", "Level")
    level = Level.objects.filter(rank__gte=DEFAULT_RANK).order_by("rank").first()
    if level is None:
        return
    apps.get_model("accounts", "LevelRule").objects.get_or_create(code=CODE, defaults={"min_level": level})


def backwards(apps, schema_editor):
    apps.get_model("accounts", "LevelRule").objects.filter(code=CODE).delete()


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0006_remove_department"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DayClose",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("work_date", models.DateField(unique=True, verbose_name="作業日")),
                ("closed_at", models.DateTimeField(auto_now_add=True, verbose_name="日結時間")),
                ("snapshot", models.JSONField(default=dict, verbose_name="日結數字")),
                (
                    "closed_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+",
                        to=settings.AUTH_USER_MODEL, verbose_name="日結人",
                    ),
                ),
            ],
            options={"verbose_name": "日結", "verbose_name_plural": "日結", "ordering": ["-work_date"]},
        ),
        migrations.RunPython(forwards, backwards),
    ]
