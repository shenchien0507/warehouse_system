# 僅供緊急備用，平常請用後台管理（/manage/）
from django.contrib import admin

from .models import Employee, JobTitle


@admin.register(JobTitle)
class JobTitleAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_no", "name", "department", "job_title", "level", "is_active")
    list_filter = ("is_active", "department", "job_title")
    search_fields = ("employee_no", "name")
