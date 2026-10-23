import django.db.models.deletion
from django.db import migrations, models

import apps.accounts.models


def forwards(apps, schema_editor):
    """舊職級數字 1–4 對應 accounts 0004 建立的職級（排序 10–40）；有帳號的人，帳號職級跟著人員資料。"""
    Level = apps.get_model("accounts", "Level")
    Employee = apps.get_model("personnel", "Employee")
    by_rank = {level.rank: level for level in Level.objects.all()}
    for employee in Employee.objects.select_related("user"):
        employee.level_ref = by_rank.get(employee.level * 10)
        employee.save(update_fields=["level_ref"])
        if employee.user_id:
            employee.user.level = employee.level_ref
            employee.user.save(update_fields=["level"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_custom_levels"),
        ("personnel", "0003_remove_job_title"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="level_ref",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="employees", to="accounts.level", verbose_name="職級",
            ),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.RemoveField(model_name="employee", name="level"),
        migrations.RenameField(model_name="employee", old_name="level_ref", new_name="level"),
        migrations.AlterField(
            model_name="employee",
            name="level",
            field=models.ForeignKey(
                blank=True, default=apps.accounts.models.lowest_level_id, null=True,
                on_delete=django.db.models.deletion.PROTECT, related_name="employees", to="accounts.level", verbose_name="職級",
            ),
        ),
    ]
