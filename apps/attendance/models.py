from django.conf import settings
from django.db import models

from apps.accounts.models import Station
from apps.personnel.models import Employee


class Status(models.TextChoices):
    PRESENT = "present", "到班"
    LEAVE = "leave", "請假"
    ABSENT = "absent", "缺勤"


class Attendance(models.Model):
    """每人每天一筆，由有帳號的人幫人員登記。當日工位可能和人員的職務不同（例如倉管支援撿貨）。"""

    employee = models.ForeignKey(Employee, verbose_name="人員", on_delete=models.PROTECT, related_name="attendances")
    date = models.DateField("日期")
    status = models.CharField("狀態", max_length=10, choices=Status.choices)
    clock_in = models.TimeField("上班時間", null=True, blank=True)
    clock_out = models.TimeField("下班時間", null=True, blank=True)
    station = models.ForeignKey(
        Station, verbose_name="當日工位", null=True, blank=True, on_delete=models.PROTECT, related_name="attendances"
    )
    note = models.CharField("備註", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="登記人", on_delete=models.PROTECT, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="最後修改人", on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField("登記時間", auto_now_add=True)
    updated_at = models.DateTimeField("最後修改時間", auto_now=True)

    class Meta:
        verbose_name = "到班紀錄"
        verbose_name_plural = "到班紀錄"
        ordering = ["-date", "employee__employee_no"]
        constraints = [models.UniqueConstraint(fields=["employee", "date"], name="unique_attendance_per_day")]

    def __str__(self):
        return f"{self.date} {self.employee} {self.get_status_display()}"


class StationBatch(models.Model):
    """工位安排的一個批次：每次「建立安排」確認儲存時，記下當時到班人員各自的工位。最新的一批就是目前生效的安排。"""

    date = models.DateField("日期")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="建立人", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        verbose_name = "工位安排批次"
        verbose_name_plural = "工位安排批次"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.date} 工位安排 {self.created_at:%H:%M}"


class StationBatchEntry(models.Model):
    batch = models.ForeignKey(StationBatch, verbose_name="批次", on_delete=models.CASCADE, related_name="entries")
    employee = models.ForeignKey(Employee, verbose_name="人員", on_delete=models.PROTECT, related_name="+")
    station = models.ForeignKey(Station, verbose_name="工位", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        verbose_name = "工位安排明細"
        verbose_name_plural = "工位安排明細"
        constraints = [models.UniqueConstraint(fields=["batch", "employee"], name="unique_employee_per_station_batch")]
