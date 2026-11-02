from django.urls import path

from . import manage_views as views

app_name = "worklog_manage"

urlpatterns = [
    path("setting/", views.WorklogSettingUpdate.as_view(), name="setting"),
]
