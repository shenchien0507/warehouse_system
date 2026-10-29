from django.urls import path

from . import views

app_name = "testdata"

urlpatterns = [
    path("", views.GenerateView.as_view(), name="generate"),
    path("simulate/", views.SimulateView.as_view(), name="simulate"),
    path("simulate/pools/", views.PoolsDownloadView.as_view(), name="simulate_pools"),
    path("simulate/round/<int:round_no>/", views.RoundDownloadView.as_view(), name="simulate_round"),
]
