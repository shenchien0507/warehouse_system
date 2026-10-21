from django.contrib.auth.models import AbstractUser
from django.db import models


class Level(models.IntegerChoices):
    """職級：數字越大，可操作範圍越大。"""

    STAFF = 1, "員工"
    LEADER = 2, "組長"
    DIRECTOR = 3, "主任"
    MANAGER = 4, "經理"
    ADMIN = 5, "管理員"


class Department(models.Model):
    name = models.CharField("部門名稱", max_length=50, unique=True)

    class Meta:
        verbose_name = "部門"
        verbose_name_plural = "部門"

    def __str__(self):
        return self.name


class Station(models.Model):
    name = models.CharField("工位名稱", max_length=50)
    department = models.ForeignKey(
        Department, verbose_name="所屬部門", on_delete=models.PROTECT, related_name="stations"
    )

    class Meta:
        verbose_name = "工位"
        verbose_name_plural = "工位"
        constraints = [
            models.UniqueConstraint(fields=["department", "name"], name="unique_station_per_department")
        ]

    def __str__(self):
        return f"{self.department}／{self.name}"


class User(AbstractUser):
    """username 即工號。離職請停用（is_active=False），不要刪除。"""

    first_name = None
    last_name = None

    name = models.CharField("姓名", max_length=50)
    phone = models.CharField("聯絡電話", max_length=30, blank=True)
    level = models.PositiveSmallIntegerField("職級", choices=Level.choices, default=Level.STAFF)
    department = models.ForeignKey(
        Department, verbose_name="部門", null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    station = models.ForeignKey(
        Station, verbose_name="工位", null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )

    class Meta:
        verbose_name = "使用者"
        verbose_name_plural = "使用者"

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.level = Level.ADMIN
        super().save(*args, **kwargs)

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name or self.username

    def __str__(self):
        return f"{self.username} {self.name}".strip()


class PagePermission(models.Model):
    """某個頁面開放給哪些部門、最低職級。由管理員在 admin 調整，新增功能不必改程式。"""

    page_key = models.SlugField("頁面代碼", max_length=50, unique=True)
    label = models.CharField("頁面名稱", max_length=50)
    min_level = models.PositiveSmallIntegerField("最低職級", choices=Level.choices, default=Level.STAFF)
    departments = models.ManyToManyField(
        Department, verbose_name="開放部門", blank=True, help_text="不選代表所有部門皆可"
    )

    class Meta:
        verbose_name = "頁面權限"
        verbose_name_plural = "頁面權限"

    def __str__(self):
        return self.label

    def allows(self, user):
        if not user.is_authenticated or not user.is_active:
            return False
        if user.level == Level.ADMIN:
            return True
        if user.level < self.min_level:
            return False
        if not self.departments.exists():
            return True
        return user.department_id is not None and self.departments.filter(pk=user.department_id).exists()
