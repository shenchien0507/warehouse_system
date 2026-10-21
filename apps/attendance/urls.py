from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.RegisterView.as_view(), name="register"),
    path("headcount/", views.HeadcountView.as_view(), name="headcount"),
]
