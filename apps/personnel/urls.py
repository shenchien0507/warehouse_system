from django.urls import path

from . import views

app_name = "personnel"

urlpatterns = [
    path("employees/", views.EmployeeList.as_view(), name="employee_list"),
    path("employees/new/", views.EmployeeCreate.as_view(), name="employee_create"),
    path("employees/<int:pk>/", views.EmployeeUpdate.as_view(), name="employee_edit"),
]
