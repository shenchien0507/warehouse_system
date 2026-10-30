from django.apps import AppConfig


class WorklogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.worklog"
    label = "worklog"
    verbose_name = "作業登記"
