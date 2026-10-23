from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("personnel", "0002_employee_level"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="employee",
            name="job_title",
        ),
        migrations.AlterField(
            model_name="employee",
            name="phone",
            field=models.CharField(blank=True, max_length=100, verbose_name="聯絡資料"),
        ),
        migrations.DeleteModel(
            name="JobTitle",
        ),
    ]
