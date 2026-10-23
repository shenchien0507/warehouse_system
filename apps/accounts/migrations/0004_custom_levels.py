import django.db.models.deletion
from django.db import migrations, models

# 舊版寫死的職級數字 → 新職級（排序拉開間隔，之後要插入新職級比較方便）
DEFAULT_LEVELS = {1: ("員工", 10), 2: ("組長", 20), 3: ("主任", 30), 4: ("經理", 40)}
OLD_ADMIN = 5
# 舊版程式寫死的門檻，改成「職級規則」的預設值
DEFAULT_RULES = {
    "attendance-register-own": 20,
    "attendance-register-all": 40,
    "attendance-past-dates": 30,
    "attendance-stations-all": 40,
}


def forwards(apps, schema_editor):
    Level = apps.get_model("accounts", "Level")
    LevelRule = apps.get_model("accounts", "LevelRule")
    User = apps.get_model("accounts", "User")
    PagePermission = apps.get_model("accounts", "PagePermission")
    levels = {old: Level.objects.create(name=name, rank=rank) for old, (name, rank) in DEFAULT_LEVELS.items()}
    by_rank = {level.rank: level for level in levels.values()}
    for code, rank in DEFAULT_RULES.items():
        LevelRule.objects.create(code=code, min_level=by_rank[rank])
    for user in User.objects.all():
        if user.level == OLD_ADMIN or user.is_superuser:
            user.is_admin = True
        user.level_ref = levels.get(user.level)
        user.save(update_fields=["is_admin", "level_ref"])
    for page in PagePermission.objects.all():
        if page.min_level in levels:
            page.min_level_ref = levels[page.min_level]
            page.save(update_fields=["min_level_ref"])
        else:
            # 最低職級是管理員的設定，等於只有管理員能用，和沒設定一樣
            page.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_station_independent"),
    ]

    operations = [
        migrations.CreateModel(
            name="Level",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50, unique=True, verbose_name="職級名稱")),
                ("rank", models.PositiveSmallIntegerField(help_text="數字越大職級越高，例如員工 10、組長 20", unique=True, verbose_name="排序")),
            ],
            options={"verbose_name": "職級", "verbose_name_plural": "職級", "ordering": ["-rank"]},
        ),
        migrations.CreateModel(
            name="LevelRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(unique=True, verbose_name="規則代碼")),
                (
                    "min_level",
                    models.ForeignKey(
                        blank=True, help_text="這個職級以上可以；空白代表只有管理員可以", null=True,
                        on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.level", verbose_name="最低職級",
                    ),
                ),
            ],
            options={"verbose_name": "職級規則", "verbose_name_plural": "職級規則"},
        ),
        migrations.AddField(
            model_name="user",
            name="is_admin",
            field=models.BooleanField(default=False, help_text="管理員可以使用所有頁面、做所有操作，不受職級限制", verbose_name="管理員"),
        ),
        migrations.AddField(
            model_name="user",
            name="level_ref",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="users", to="accounts.level", verbose_name="職級",
            ),
        ),
        migrations.AddField(
            model_name="pagepermission",
            name="min_level_ref",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.level", verbose_name="最低職級",
            ),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.RemoveField(model_name="user", name="level"),
        migrations.RemoveField(model_name="pagepermission", name="min_level"),
        migrations.RenameField(model_name="user", old_name="level_ref", new_name="level"),
        migrations.RenameField(model_name="pagepermission", old_name="min_level_ref", new_name="min_level"),
        migrations.AlterField(
            model_name="pagepermission",
            name="min_level",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.level", verbose_name="最低職級"),
        ),
    ]
