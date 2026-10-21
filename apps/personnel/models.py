from django.conf import settings
from django.db import models

from apps.accounts.models import Department


class JobTitle(models.Model):
    """應徵進來的職務（倉管、撿貨員…）。每天實際站的工位另外記，可能和職務不同。"""

    name = models.CharField("職務名稱", max_length=50, unique=True)

    class Meta:
        verbose_name = "職務"
        verbose_name_plural = "職務"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Employee(models.Model):
    """人員資料。不是每個人都有系統帳號；需要操作系統的人才另外開帳號並連結。離職請改為停用，不要刪除。"""

    employee_no = models.CharField("工號", max_length=30, unique=True)
    name = models.CharField("姓名", max_length=50)
    department = models.ForeignKey(
        Department, verbose_name="部門", null=True, blank=True, on_delete=models.PROTECT, related_name="employees"
    )
    job_title = models.ForeignKey(
        JobTitle, verbose_name="職務", null=True, blank=True, on_delete=models.PROTECT, related_name="employees"
    )
    phone = models.CharField("聯絡電話", max_length=30, blank=True)
    hire_date = models.DateField("到職日", null=True, blank=True)
    is_active = models.BooleanField("在職", default=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="系統帳號",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employee",
        help_text="有操作系統的人才需要連結帳號",
    )
    note = models.TextField("備註", blank=True)

    class Meta:
        verbose_name = "人員"
        verbose_name_plural = "人員"
        ordering = ["employee_no"]

    def __str__(self):
        return f"{self.employee_no} {self.name}"
