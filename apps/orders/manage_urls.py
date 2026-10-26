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
    path("categories/", views.CategoryList.as_view(), name="category_list"),
    path("categories/new/", views.CategoryCreate.as_view(), name="category_create"),
    path("categories/<int:pk>/", views.CategoryUpdate.as_view(), name="category_edit"),
    path("categories/<int:pk>/delete/", views.CategoryDelete.as_view(), name="category_delete"),
    path("groups/", views.GroupVersionList.as_view(), name="group_version_list"),
    path("groups/new/", views.GroupVersionCreate.as_view(), name="group_version_create"),
    path("groups/<int:pk>/", views.GroupVersionDetail.as_view(), name="group_version_detail"),
    path("groups/<int:pk>/source/", views.GroupVersionSource.as_view(), name="group_version_source"),
    path("groups/<int:pk>/activate/", views.GroupVersionActivate.as_view(), name="group_version_activate"),
    path("groups/<int:pk>/copy/", views.GroupVersionCopy.as_view(), name="group_version_copy"),
    path("groups/<int:pk>/delete/", views.GroupVersionDelete.as_view(), name="group_version_delete"),
    path("groups/<int:version_pk>/group/new/", views.GroupCreate.as_view(), name="group_create"),
    path("groups/<int:version_pk>/group/<int:pk>/", views.GroupUpdate.as_view(), name="group_edit"),
    path("groups/<int:version_pk>/group/<int:pk>/delete/", views.GroupDelete.as_view(), name="group_delete"),
]
