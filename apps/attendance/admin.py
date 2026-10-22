# 僅供緊急備用，平常請用到班登記頁面
from django.contrib import admin

from .models import Attendance, AttendanceEvent


class AttendanceEventInline(admin.TabularInline):
    model = AttendanceEvent
    extra = 0


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    inlines = [AttendanceEventInline]
    list_display = ("date", "employee", "status", "clock_in", "clock_out", "on_site", "station", "updated_by")
    list_filter = ("date", "status", "employee__department")
    search_fields = ("employee__employee_no", "employee__name")
