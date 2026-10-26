import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

DEFAULT_CATEGORIES = ["急單", "出貨中", "新訂單"]


def seed_and_link(apps, schema_editor):
    """預設三個匯入分類；舊的每一批各自變成一筆統計紀錄（沒有分類）。"""
    ImportCategory = apps.get_model("orders", "ImportCategory")
    StatRun = apps.get_model("orders", "StatRun")
    ImportBatch = apps.get_model("orders", "ImportBatch")
    for i, name in enumerate(DEFAULT_CATEGORIES, start=1):
        ImportCategory.objects.get_or_create(name=name, defaults={"sort_order": i * 10})
    for batch in ImportBatch.objects.all():
        run = StatRun.objects.create(work_date=batch.work_date, created_by_id=batch.imported_by_id)
        StatRun.objects.filter(pk=run.pk).update(created_at=batch.imported_at)  # auto_now_add 只能建好再改
        batch.run = run
        batch.save(update_fields=["run"])


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0010_group_carry_over_split_by_day"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ImportCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50, unique=True, verbose_name="分類名稱")),
                ("sort_order", models.PositiveIntegerField(default=0, help_text="數字小的排前面，匯入畫面和統計頁都照這個順序。", verbose_name="顯示順序")),
                ("is_active", models.BooleanField(default=True, help_text="停用後匯入畫面不再出現這個分類，舊的統計紀錄照樣保留。", verbose_name="使用中")),
            ],
            options={"verbose_name": "匯入分類", "verbose_name_plural": "匯入分類", "ordering": ["sort_order", "pk"]},
        ),
        migrations.CreateModel(
            name="StatRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("work_date", models.DateField(verbose_name="作業日")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="匯入時間")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="匯入人")),
            ],
            options={"verbose_name": "統計紀錄", "verbose_name_plural": "統計紀錄", "ordering": ["-created_at", "-pk"]},
        ),
        migrations.AddField(
            model_name="importbatch", name="category",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="batches", to="orders.importcategory", verbose_name="分類"),
        ),
        migrations.AddField(
            model_name="importbatch", name="category_name",
            field=models.CharField(blank=True, max_length=50, verbose_name="分類名稱"),
        ),
        migrations.AddField(
            model_name="importbatch", name="run",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="batches", to="orders.statrun", verbose_name="統計紀錄"),
        ),
        migrations.RunPython(seed_and_link, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="importbatch", name="run",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="batches", to="orders.statrun", verbose_name="統計紀錄"),
        ),
    ]
