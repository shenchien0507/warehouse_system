from django.urls import path

from . import views

app_name = "orders_manage"

urlpatterns = [
    path("mapping/", views.VersionList.as_view(), name="version_list"),
    path("mapping/new/", views.VersionCreate.as_view(), name="version_create"),
    path("mapping/<int:pk>/", views.VersionDetail.as_view(), name="version_detail"),
    path("mapping/<int:pk>/check/", views.VersionCheck.as_view(), name="version_check"),
    path("mapping/<int:pk>/activate/", views.VersionActivate.as_view(), name="version_activate"),
    path("mapping/<int:pk>/copy/", views.VersionCopy.as_view(), name="version_copy"),
    path("mapping/<int:pk>/delete/", views.VersionDelete.as_view(), name="version_delete"),
    path("groups/", views.GroupList.as_view(), name="group_list"),
    path("groups/new/", views.GroupCreate.as_view(), name="group_create"),
    path("groups/<int:pk>/", views.GroupUpdate.as_view(), name="group_edit"),
    path("groups/<int:pk>/delete/", views.GroupDelete.as_view(), name="group_delete"),
]
