from django.urls import path

from . import group_views, manage_views

app_name = "orders_manage"

urlpatterns = [
    path("mapping/", manage_views.VersionList.as_view(), name="version_list"),
    path("mapping/new/", manage_views.VersionCreate.as_view(), name="version_create"),
    path("mapping/<int:pk>/", manage_views.VersionDetail.as_view(), name="version_detail"),
    path("mapping/<int:pk>/check/", manage_views.VersionCheck.as_view(), name="version_check"),
    path("mapping/<int:pk>/activate/", manage_views.VersionActivate.as_view(), name="version_activate"),
    path("mapping/<int:pk>/copy/", manage_views.VersionCopy.as_view(), name="version_copy"),
    path("mapping/<int:pk>/delete/", manage_views.VersionDelete.as_view(), name="version_delete"),
    path("categories/", manage_views.CategoryList.as_view(), name="category_list"),
    path("categories/new/", manage_views.CategoryCreate.as_view(), name="category_create"),
    path("categories/<int:pk>/", manage_views.CategoryUpdate.as_view(), name="category_edit"),
    path("categories/<int:pk>/delete/", manage_views.CategoryDelete.as_view(), name="category_delete"),
    path("groups/", group_views.GroupVersionList.as_view(), name="group_version_list"),
    path("groups/new/", group_views.GroupVersionCreate.as_view(), name="group_version_create"),
    path("groups/<int:pk>/", group_views.GroupVersionDetail.as_view(), name="group_version_detail"),
    path("groups/<int:pk>/source/", group_views.GroupVersionSource.as_view(), name="group_version_source"),
    path("groups/<int:pk>/activate/", group_views.GroupVersionActivate.as_view(), name="group_version_activate"),
    path("groups/<int:pk>/copy/", group_views.GroupVersionCopy.as_view(), name="group_version_copy"),
    path("groups/<int:pk>/delete/", group_views.GroupVersionDelete.as_view(), name="group_version_delete"),
    path("groups/<int:version_pk>/group/new/", group_views.GroupCreate.as_view(), name="group_create"),
    path("groups/<int:version_pk>/group/<int:pk>/", group_views.GroupUpdate.as_view(), name="group_edit"),
    path("groups/<int:version_pk>/group/<int:pk>/delete/", group_views.GroupDelete.as_view(), name="group_delete"),
]
