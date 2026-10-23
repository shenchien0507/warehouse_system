# 僅供緊急備用，平常請用後台管理（/manage/）
from django.contrib import admin

from .models import Employee


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_no", "name", "level", "department", "is_active")
    list_filter = ("is_active", "level", "department")
    search_fields = ("employee_no", "name")
