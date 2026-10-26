from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", views.BatchListView.as_view(), name="batch_list"),
    path("<int:pk>/", views.BatchDetailView.as_view(), name="batch_detail"),
    path("<int:pk>/delete/", views.BatchDeleteView.as_view(), name="batch_delete"),
]
