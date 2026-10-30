from django.urls import path

from . import views

app_name = "records"

urlpatterns = [
    path("", views.RecordListView.as_view(), name="list"),
    path("new/", views.RecordGridView.as_view(), name="new"),
    path("<int:pk>/edit/", views.RecordEditView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.RecordDeleteView.as_view(), name="delete"),
]
