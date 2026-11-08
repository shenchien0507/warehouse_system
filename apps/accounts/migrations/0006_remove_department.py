from django.db import migrations

# 拿掉部門後，到班登記不再分「自己部門／全部部門」，合併成一條「登記人員」規則，門檻沿用原本較低的「登記自己部門」；
# 「安排全部部門」只剩強制解除編輯鎖的用途，改名但門檻不變。
RENAMES = {"attendance-register-own": "attendance-register", "attendance-stations-all": "attendance-stations-unlock"}
REMOVED = ["attendance-register-all"]


def forwards(apps, schema_editor):
    LevelRule = apps.get_model("accounts", "LevelRule")
    PagePermission = apps.get_model("accounts", "PagePermission")
    for old, new in RENAMES.items():
        if not LevelRule.objects.filter(code=new).exists():
            LevelRule.objects.filter(code=old).update(code=new)
    LevelRule.objects.filter(code__in=REMOVED + list(RENAMES)).delete()
    PagePermission.objects.filter(page_key="manage-departments").delete()


def backwards(apps, schema_editor):
    LevelRule = apps.get_model("accounts", "LevelRule")
    for old, new in RENAMES.items():
        LevelRule.objects.filter(code=new).update(code=old)
    register = LevelRule.objects.filter(code="attendance-register-own").first()
    if register:
        LevelRule.objects.get_or_create(code="attendance-register-all", defaults={"min_level": register.min_level})


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_level_rank_range"),
        ("personnel", "0005_remove_department"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name="pagepermission",
            name="departments",
        ),
        migrations.RemoveField(
            model_name="user",
            name="department",
        ),
        migrations.DeleteModel(
            name="Department",
        ),
    ]
