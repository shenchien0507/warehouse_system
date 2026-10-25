from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.RegisterView.as_view(), name="register"),
    path("list/", views.PersonListView.as_view(), name="list"),
    path("stations/", views.StationListView.as_view(), name="stations"),
    path("stations/new/", views.StationCreateView.as_view(), name="station_new"),
    path("stations/lock/", views.StationLockView.as_view(), name="station_lock"),
    # 到班人數已併入到班登記頁
    path("headcount/", RedirectView.as_view(pattern_name="attendance:register", query_string=True), name="headcount"),
]
