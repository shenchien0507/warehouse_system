from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Department, PagePermission, Station, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "name", "level", "department", "station", "is_active")
    list_filter = ("level", "department", "is_active")
    search_fields = ("username", "name")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("個人資料", {"fields": ("name", "email", "phone")}),
        ("職級與所屬", {"fields": ("level", "department", "station")}),
        ("狀態", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("重要日期", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("username", "name", "level", "department", "station", "password1", "password2")}),
    )


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ("name", "department")
    list_filter = ("department",)


@admin.register(PagePermission)
class PagePermissionAdmin(admin.ModelAdmin):
    list_display = ("label", "page_key", "min_level")
    filter_horizontal = ("departments",)
