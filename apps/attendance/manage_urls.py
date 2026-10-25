from django.urls import path

from . import manage_views as views

app_name = "attendance_manage"

urlpatterns = [
    path("clock-setting/", views.ClockSettingUpdate.as_view(), name="clock_setting"),
]
