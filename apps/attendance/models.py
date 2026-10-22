from django.conf import settings
from django.db import models

from apps.accounts.models import Station
from apps.personnel.models import Employee


class Status(models.TextChoices):
    """當天狀態，由當天的紀錄算出來，不用手動選。"""

    PRESENT = "present", "到班"
    PARTIAL = "partial", "部分請假"
    LEAVE = "leave", "請假"
    ABSENT = "absent", "缺勤"


PRESENT_STATUSES = (Status.PRESENT, Status.PARTIAL)  # 今天有來過現場


class EventKind(models.TextChoices):
    CLOCK_IN = "clock_in", "上班"
    CLOCK_OUT = "clock_out", "下班"
    LEAVE_OUT = "leave_out", "請假離開"
    LEAVE = "leave", "請假"
    ABSENT = "absent", "缺勤"


IN_KINDS = (EventKind.CLOCK_IN,)
OUT_KINDS = (EventKind.CLOCK_OUT, EventKind.LEAVE_OUT)


class Attendance(models.Model):
    """每人每天一筆，底下是當天的紀錄（上班、下班、請假…），只累加不覆蓋。
    狀態、上下班時間、是否在場都由紀錄算出來存在這裡，方便統計。當日工位可能和人員的職務不同（例如倉管支援撿貨）。"""

    employee = models.ForeignKey(Employee, verbose_name="人員", on_delete=models.PROTECT, related_name="attendances")
    date = models.DateField("日期")
    status = models.CharField("狀態", max_length=10, choices=Status.choices, blank=True)
    clock_in = models.TimeField("第一次上班", null=True, blank=True)
    clock_out = models.TimeField("最後離開", null=True, blank=True)
    on_site = models.BooleanField("目前在場", default=False)
    station = models.ForeignKey(
        Station, verbose_name="當日工位", null=True, blank=True, on_delete=models.PROTECT, related_name="attendances"
    )
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

    def active_events(self):
        return [e for e in self.events.all() if e.voided_at is None]

    def refresh(self):
        """依未作廢的紀錄重算狀態、上下班時間與是否在場。"""
        events = self.active_events()
        kinds = {e.kind for e in events}
        presence = [e for e in events if e.kind in IN_KINDS + OUT_KINDS]
        if EventKind.CLOCK_IN in kinds:
            self.status = Status.PARTIAL if kinds & {EventKind.LEAVE, EventKind.LEAVE_OUT} else Status.PRESENT
        elif EventKind.LEAVE in kinds:
            self.status = Status.LEAVE
        elif EventKind.ABSENT in kinds:
            self.status = Status.ABSENT
        else:
            self.status = ""
        self.clock_in = next((e.time for e in presence if e.kind in IN_KINDS), None)
        self.on_site = bool(presence) and presence[-1].kind in IN_KINDS
        self.clock_out = presence[-1].time if presence and not self.on_site else None


class AttendanceEvent(models.Model):
    """當天的一筆紀錄。登記錯了用作廢，不刪除。"""

    attendance = models.ForeignKey(Attendance, verbose_name="到班紀錄", on_delete=models.CASCADE, related_name="events")
    kind = models.CharField("類型", max_length=10, choices=EventKind.choices)
    time = models.TimeField("時間", null=True, blank=True, help_text="請假的開始時間；全天請假與缺勤可空白")
    end_time = models.TimeField("結束時間", null=True, blank=True, help_text="只有請假用")
    note = models.CharField("原因／備註", max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="登記人", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField("登記時間", auto_now_add=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="作廢人", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    voided_at = models.DateTimeField("作廢時間", null=True, blank=True)

    class Meta:
        verbose_name = "到班明細"
        verbose_name_plural = "到班明細"
        ordering = [models.F("time").asc(nulls_first=True), "created_at", "pk"]

    def __str__(self):
        return f"{self.attendance.date} {self.attendance.employee} {self.describe()}"

    def describe(self):
        """例如「上班 08:00」「請假 08:00–12:00」「全天請假」。"""
        if self.kind == EventKind.LEAVE:
            if self.time and self.end_time:
                return f"請假 {self.time:%H:%M}–{self.end_time:%H:%M}"
            if self.time:
                return f"請假 {self.time:%H:%M} 起"
            if self.end_time:
                return f"請假 至 {self.end_time:%H:%M}"
            return "全天請假"
        if self.time:
            return f"{self.get_kind_display()} {self.time:%H:%M}"
        return self.get_kind_display()


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
