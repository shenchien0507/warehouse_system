"""作業登記（撿貨、配貨）：同一個編號第一次刷記開始，再刷一次記結束；每個階段只走一輪，走完再刷會擋下。
兩個階段共用同一張表，用 stage 區分；編號存文字，登記當下比對（撿貨比對登記紀錄、配貨比對撿貨），不用外鍵綁住。"""

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models


class Stage(models.TextChoices):
    PICKING = "picking", "撿貨"
    ALLOCATION = "allocation", "配貨"


class WorkEntry(models.Model):
    stage = models.CharField("階段", max_length=20, choices=Stage.choices)
    number = models.CharField("編號", max_length=50)
    start_employee = models.ForeignKey(
        "personnel.Employee", verbose_name="開始員工", on_delete=models.PROTECT, related_name="+"
    )
    started_at = models.DateTimeField("開始時間", auto_now_add=True)
    end_employee = models.ForeignKey(
        "personnel.Employee", verbose_name="結束員工", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    ended_at = models.DateTimeField("結束時間", null=True, blank=True)
    # 配貨開始時，撿貨那邊同編號還沒刷結束：照樣登記，記下異常（只有職級規則允許的人看得到）
    anomaly = models.BooleanField("異常", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="登記帳號", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="最後修改人", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField("最後修改時間", auto_now=True)

    class Meta:
        verbose_name = "作業登記"
        verbose_name_plural = "作業登記"
        ordering = ["-started_at", "-pk"]
        indexes = [models.Index(fields=["stage", "number"])]

    def __str__(self):
        return f"{self.get_stage_display()} {self.number}"

    @property
    def is_open(self):
        return self.ended_at is None

    @property
    def edited(self):
        return self.updated_by_id is not None


class WorklogSetting(models.Model):
    """撿貨、配貨的設定（全公司一組）：同一個編號刷完後幾秒內再刷不算，避免條碼槍連刷或 Enter 按兩次就直接結束。"""

    rescan_seconds = models.PositiveSmallIntegerField(
        "重複刷的間隔（秒）", default=10, validators=[MaxValueValidator(600)],
        help_text="同一個編號在同一個階段刷過之後，這幾秒內再刷會被擋下；填 0 不限制",
    )

    class Meta:
        verbose_name = "撿貨配貨設定"
        verbose_name_plural = "撿貨配貨設定"

    def __str__(self):
        return "撿貨配貨設定"

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]
