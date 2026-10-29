from django.apps import AppConfig


class TestdataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.testdata"
    label = "testdata"
    verbose_name = "測試資料產生"
