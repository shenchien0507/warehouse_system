from django.urls import path

from apps.daily.urls import DateConverter  # noqa: F401（註冊 date 轉換器）

from . import views

app_name = "closing"

urlpatterns = [
    path("", views.ClosingView.as_view(), name="index"),
    path("close/", views.CloseDayView.as_view(), name="close"),
    path("<date:work_date>/", views.ReportView.as_view(), name="report"),
    path("<date:work_date>/cancel/", views.CancelCloseView.as_view(), name="cancel"),
]
