from django.contrib.auth.models import AbstractUser
from django.db import models


class Level(models.Model):
    """職級，由管理員在後台「職級」新增、改名、調整高低。排序數字越大職級越高，權限依高低判斷。
    「管理員」不是職級，是系統帳號上的身分（User.is_admin）。"""

    name = models.CharField("職級名稱", max_length=50, unique=True)
    rank = models.PositiveSmallIntegerField("排序", unique=True, help_text="數字越大職級越高，例如員工 10、組長 20")

    class Meta:
        verbose_name = "職級"
        verbose_name_plural = "職級"
        ordering = ["-rank"]

    def __str__(self):
        return self.name


def lowest_level_id():
    """新人員預設最低的職級。"""
    return Level.objects.order_by("rank").values_list("pk", flat=True).first()


class LevelRule(models.Model):
    """程式裡依職級判斷的規則（例如「可登記全部部門」），門檻職級由管理員在後台「職級規則」設定。
    規則代碼列在 apps/accounts/levels.py 的 RULES；沒設門檻代表只有管理員可以。"""

    code = models.SlugField("規則代碼", max_length=50, unique=True)
    min_level = models.ForeignKey(
        Level, verbose_name="最低職級", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="這個職級以上可以；空白代表只有管理員可以",
    )

    class Meta:
        verbose_name = "職級規則"
        verbose_name_plural = "職級規則"

    def __str__(self):
        return self.code


class Department(models.Model):
    name = models.CharField("部門名稱", max_length=50, unique=True)

    class Meta:
        verbose_name = "部門"
        verbose_name_plural = "部門"

    def __str__(self):
        return self.name


class Station(models.Model):
    """工位和部門、職級各自獨立，任何部門的人都可以排到任何工位。"""

    name = models.CharField("工位名稱", max_length=50, unique=True)

    class Meta:
        verbose_name = "工位"
        verbose_name_plural = "工位"

    def __str__(self):
        return self.name


class User(AbstractUser):
    """username 即工號。離職請停用（is_active=False），不要刪除。"""

    first_name = None
    last_name = None

    name = models.CharField("姓名", max_length=50)
    phone = models.CharField("聯絡資料", max_length=100, blank=True)
    level = models.ForeignKey(
        Level, verbose_name="職級", null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    is_admin = models.BooleanField("管理員", default=False, help_text="管理員可以使用所有頁面、做所有操作，不受職級限制")
    department = models.ForeignKey(
        Department, verbose_name="部門", null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )

    class Meta:
        verbose_name = "使用者"
        verbose_name_plural = "使用者"

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.is_admin = True
        super().save(*args, **kwargs)

    @property
    def level_display(self):
        return "管理員" if self.is_admin else (self.level.name if self.level_id else "未設定職級")

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name or self.username

    def __str__(self):
        return f"{self.username} {self.name}".strip()


class PagePermission(models.Model):
    """某個頁面開放給哪些部門、最低職級。由管理員在後台「頁面權限」調整，新增功能不必改程式。"""

    page_key = models.SlugField("頁面代碼", max_length=50, unique=True)
    label = models.CharField("頁面名稱", max_length=50)
    min_level = models.ForeignKey(Level, verbose_name="最低職級", on_delete=models.PROTECT, related_name="+")
    departments = models.ManyToManyField(
        Department, verbose_name="開放部門", blank=True, help_text="不選代表所有部門皆可"
    )

    class Meta:
        verbose_name = "頁面權限"
        verbose_name_plural = "頁面權限"

    def __str__(self):
        return self.label

    def allows(self, user):
        from .levels import is_admin, reaches

        if not user.is_authenticated or not user.is_active:
            return False
        if is_admin(user):
            return True
        if not reaches(user, self.min_level):
            return False
        if not self.departments.exists():
            return True
        return user.department_id is not None and self.departments.filter(pk=user.department_id).exists()
