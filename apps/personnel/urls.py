from django.urls import path

from . import views

app_name = "personnel"

urlpatterns = [
    path("employees/", views.EmployeeList.as_view(), name="employee_list"),
    path("employees/new/", views.EmployeeCreate.as_view(), name="employee_create"),
    path("employees/<int:pk>/", views.EmployeeUpdate.as_view(), name="employee_edit"),
    path("job-titles/", views.JobTitleList.as_view(), name="job_title_list"),
    path("job-titles/new/", views.JobTitleCreate.as_view(), name="job_title_create"),
    path("job-titles/<int:pk>/", views.JobTitleUpdate.as_view(), name="job_title_edit"),
    path("job-titles/<int:pk>/delete/", views.JobTitleDelete.as_view(), name="job_title_delete"),
]
