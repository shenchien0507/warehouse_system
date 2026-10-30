from datetime import date

from django.urls import path, register_converter

from . import views


class DateConverter:
    regex = r"\d{4}-\d{2}-\d{2}"

    def to_python(self, value):
        return date.fromisoformat(value)

    def to_url(self, value):
        return value.isoformat()


register_converter(DateConverter, "date")

app_name = "daily"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="day_list"),
    path("<date:work_date>/", views.DashboardView.as_view(), name="day_detail"),
    path("batch/<int:pk>/delete/", views.BatchDeleteView.as_view(), name="batch_delete"),
    path("order/<int:pk>/hold/", views.HoldView.as_view(), name="hold"),
    path("hold/<int:pk>/release/", views.ReleaseView.as_view(), name="release"),
]
