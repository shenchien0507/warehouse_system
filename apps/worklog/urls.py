from django.urls import path

from . import views
from .models import Stage

app_name = "worklog"

# 每個階段一組網址（worklog:picking、worklog:picking_edit…），導覽列直接用名稱連過去
urlpatterns = []
for stage in Stage.values:
    urlpatterns += [
        path(f"{stage}/", views.StagePageView.as_view(), {"stage": stage}, name=stage),
        path(f"{stage}/<int:pk>/edit/", views.EntryEditView.as_view(), {"stage": stage}, name=f"{stage}_edit"),
        path(f"{stage}/<int:pk>/delete/", views.EntryDeleteView.as_view(), {"stage": stage}, name=f"{stage}_delete"),
    ]
