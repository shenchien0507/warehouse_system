from django.apps import AppConfig


class DailyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.daily"
    label = "daily"
    verbose_name = "當日統計"
