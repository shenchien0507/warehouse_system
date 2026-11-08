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

    @property
    def segment_list(self):
        """這筆的作業片段（照時間順序）；列表頁有 prefetch_related("segments__employee") 時不會再查資料庫。"""
        return sorted(self.segments.all(), key=lambda s: (s.started_at, s.pk))

    @property
    def current_employee(self):
        """現在負責的人：最後一段的員工（還沒結束就是正在做的人）。"""
        segments = self.segment_list
        return segments[-1].employee if segments else self.start_employee

    @property
    def handovers(self):
        """有交接時回傳片段清單，沒交接（只有一段）回傳空清單。"""
        segments = self.segment_list
        return segments if len(segments) > 1 else []


class WorkSegment(models.Model):
    """作業片段：一筆撿貨或配貨裡，每個人實際做的那一段。
    同一個人再刷一次是完成；換別人刷是交接，前一段記成交接，接手的人開新的一段，等他再刷一次才完成。
    之後要算個人產能，就用每段的時間（開始到結束）。"""

    HANDOVER = "handover"
    DONE = "done"
    OUTCOMES = [(HANDOVER, "交接"), (DONE, "完成")]

    entry = models.ForeignKey(WorkEntry, verbose_name="作業登記", on_delete=models.CASCADE, related_name="segments")
    employee = models.ForeignKey("personnel.Employee", verbose_name="員工", on_delete=models.PROTECT, related_name="+")
    started_at = models.DateTimeField("開始時間")
    ended_at = models.DateTimeField("結束時間", null=True, blank=True)
    outcome = models.CharField("結束方式", max_length=20, choices=OUTCOMES, blank=True)

    class Meta:
        verbose_name = "作業片段"
        verbose_name_plural = "作業片段"
        ordering = ["started_at", "pk"]

    def __str__(self):
        return f"{self.entry} {self.employee.employee_no}"


class WorklogSetting(models.Model):
    """撿貨、配貨的設定（全公司一組）：同一個編號刷完後幾秒內再刷不算，避免條碼槍連刷或 Enter 按兩次就直接結束。"""

    rescan_seconds = models.PositiveSmallIntegerField(
        "重複刷的間隔（秒）", default=10, validators=[MaxValueValidator(600)],
        help_text="同一個編號在同一個階段刷過之後，這幾秒內再刷會被擋下；填 0 不限制",
    )
    # 員工編號當天工位（工位安排目前生效的那批）要在這裡面才能登記；沒勾任何工位 = 不限制
    picking_stations = models.ManyToManyField(
        "accounts.Station", verbose_name="撿貨可登記的工位", blank=True, related_name="+",
        help_text="員工今天的工位要是勾選的其中一個，才能在撿貨登記刷開始或結束；都不勾 = 不限制",
    )
    allocation_stations = models.ManyToManyField(
        "accounts.Station", verbose_name="配貨可登記的工位", blank=True, related_name="+",
        help_text="員工今天的工位要是勾選的其中一個，才能在配貨登記刷開始或結束；都不勾 = 不限制",
    )

    class Meta:
        verbose_name = "撿貨配貨設定"
        verbose_name_plural = "撿貨配貨設定"

    def __str__(self):
        return "撿貨配貨設定"

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def stations_for(self, stage):
        field = self.picking_stations if stage == Stage.PICKING else self.allocation_stations
        return list(field.order_by("name"))
