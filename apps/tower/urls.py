from django.urls import path

from . import views

app_name = "tower"

urlpatterns = [path("", views.TowerView.as_view(), name="index")]
