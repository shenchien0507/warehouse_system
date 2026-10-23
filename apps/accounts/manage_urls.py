from django.urls import path

from . import manage_views as views

app_name = "accounts_manage"

urlpatterns = [
    path("levels/", views.LevelList.as_view(), name="level_list"),
    path("levels/new/", views.LevelCreate.as_view(), name="level_create"),
    path("levels/<int:pk>/", views.LevelUpdate.as_view(), name="level_edit"),
    path("levels/<int:pk>/delete/", views.LevelDelete.as_view(), name="level_delete"),
    path("level-rules/", views.LevelRuleList.as_view(), name="level_rule_list"),
    path("level-rules/<slug:code>/", views.LevelRuleUpdate.as_view(), name="level_rule_edit"),
    path("departments/", views.DepartmentList.as_view(), name="department_list"),
    path("departments/new/", views.DepartmentCreate.as_view(), name="department_create"),
    path("departments/<int:pk>/", views.DepartmentUpdate.as_view(), name="department_edit"),
    path("departments/<int:pk>/delete/", views.DepartmentDelete.as_view(), name="department_delete"),
    path("stations/", views.StationList.as_view(), name="station_list"),
    path("stations/new/", views.StationCreate.as_view(), name="station_create"),
    path("stations/<int:pk>/", views.StationUpdate.as_view(), name="station_edit"),
    path("stations/<int:pk>/delete/", views.StationDelete.as_view(), name="station_delete"),
    path("users/", views.UserList.as_view(), name="user_list"),
    path("users/new/", views.UserCreate.as_view(), name="user_create"),
    path("users/<int:pk>/", views.UserUpdate.as_view(), name="user_edit"),
    path("users/<int:pk>/password/", views.UserPassword.as_view(), name="user_password"),
    path("permissions/", views.PagePermissionList.as_view(), name="page_permission_list"),
    path("permissions/new/", views.PagePermissionCreate.as_view(), name="page_permission_create"),
    path("permissions/<int:pk>/", views.PagePermissionUpdate.as_view(), name="page_permission_edit"),
    path("permissions/<int:pk>/delete/", views.PagePermissionDelete.as_view(), name="page_permission_delete"),
]
