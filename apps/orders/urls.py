from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", views.RunListView.as_view(), name="run_list"),
    path("<int:pk>/", views.RunDetailView.as_view(), name="run_detail"),
    path("<int:pk>/delete/", views.RunDeleteView.as_view(), name="run_delete"),
]
