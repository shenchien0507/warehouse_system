from django.db import migrations, models


def rename_duplicate_stations(apps, schema_editor):
    """工位不再屬於部門、名稱要唯一：不同部門有同名工位時，改成「部門／工位」保留區別。"""
    Station = apps.get_model("accounts", "Station")
    names = {}
    for station in Station.objects.select_related("department").order_by("pk"):
        names.setdefault(station.name, []).append(station)
    for stations in names.values():
        if len(stations) > 1:
            for station in stations:
                station.name = f"{station.department.name}／{station.name}"[:50]
                station.save(update_fields=["name"])


def job_titles_to_levels(apps, schema_editor):
    """組織選單的「職務」換成「職級」：原本職務頁的權限設定改給職級頁。"""
    PagePermission = apps.get_model("accounts", "PagePermission")
    if not PagePermission.objects.filter(page_key="manage-levels").exists():
        PagePermission.objects.filter(page_key="manage-job-titles").update(page_key="manage-levels", label="職級")
    PagePermission.objects.filter(page_key="manage-job-titles").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_remove_user_station"),
    ]

    operations = [
        migrations.RunPython(rename_duplicate_stations, migrations.RunPython.noop),
        migrations.RunPython(job_titles_to_levels, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="station",
            name="unique_station_per_department",
        ),
        migrations.RemoveField(
            model_name="station",
            name="department",
        ),
        migrations.AlterField(
            model_name="station",
            name="name",
            field=models.CharField(max_length=50, unique=True, verbose_name="工位名稱"),
        ),
        migrations.AlterField(
            model_name="user",
            name="phone",
            field=models.CharField(blank=True, max_length=100, verbose_name="聯絡資料"),
        ),
    ]
