from django.urls import path

from . import views

app_name = "testdata"

urlpatterns = [
    path("", views.GenerateView.as_view(), name="generate"),
]
