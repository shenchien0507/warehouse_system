from django.conf import settings
from django.db import models

from apps.accounts.models import Department, Level, lowest_level_id


class Employee(models.Model):
    """人員資料。不是每個人都有系統帳號；需要操作系統的人才另外開帳號並連結。離職請改為停用，不要刪除。"""

    employee_no = models.CharField("工號", max_length=30, unique=True)
    name = models.CharField("姓名", max_length=50)
    department = models.ForeignKey(
        Department, verbose_name="部門", null=True, blank=True, on_delete=models.PROTECT, related_name="employees"
    )
    level = models.ForeignKey(
        Level, verbose_name="職級", null=True, blank=True, default=lowest_level_id, on_delete=models.PROTECT, related_name="employees"
    )
    phone = models.CharField("聯絡資料", max_length=100, blank=True)
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

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # 工號、姓名、聯絡資料、部門、職級以人員資料為準，有帳號時同步過去（管理員是帳號身分，不受影響）
        # 離職時帳號一併停用（管理員帳號除外）；復職不會自動啟用，要到系統帳號手動打開
        if self.user_id:
            user = self.user
            synced = {
                "username": self.employee_no, "name": self.name, "phone": self.phone,
                "department_id": self.department_id, "level_id": self.level_id,
            }
            if not user.is_admin:
                if not self.is_active:
                    synced["is_active"] = False
            if any(getattr(user, field) != value for field, value in synced.items()):
                for field, value in synced.items():
                    setattr(user, field, value)
                user.save(update_fields=list(synced))
