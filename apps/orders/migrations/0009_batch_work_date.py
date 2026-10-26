from django.db import migrations, models
from django.utils import timezone


def fill_work_date(apps, schema_editor):
    """舊批次的作業日就是匯入那天。"""
    ImportBatch = apps.get_model("orders", "ImportBatch")
    for batch in ImportBatch.objects.all():
        batch.work_date = timezone.localtime(batch.imported_at).date()
        batch.save(update_fields=["work_date"])


class Migration(migrations.Migration):
    dependencies = [("orders", "0008_group_version_source")]

    operations = [
        migrations.AddField(model_name="importbatch", name="work_date", field=models.DateField("作業日", null=True)),
        migrations.RunPython(fill_work_date, migrations.RunPython.noop),
        migrations.AlterField(model_name="importbatch", name="work_date", field=models.DateField("作業日")),
    ]
