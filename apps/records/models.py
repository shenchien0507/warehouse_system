"""登記紀錄：單純打什麼記什麼的表格，不和其他資料表用外鍵關聯；種類只記統計分組的名稱，給當日統計、數據塔對帳用。
編號不能重複；日期存成純文字，輸入什麼就存什麼，不轉換、不檢查格式；操作人取自登入的帳號。"""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class RecordQuerySet(models.QuerySet):
    def created_on(self, day):
        """某天（台灣時間）登記的紀錄。不用 created_at__date：MySQL 沒載入時區表時 CONVERT_TZ 回傳 NULL，會一筆都對不到。"""
        start = timezone.make_aware(datetime.combine(day, time.min))
        return self.filter(created_at__gte=start, created_at__lt=start + timedelta(days=1))


class Record(models.Model):
    number = models.CharField("編號", max_length=50, unique=True, error_messages={"unique": "這個編號已經登記過了。"})
    date_text = models.CharField("日期", max_length=50, blank=True)
    name = models.CharField("名稱", max_length=200)
    quantity = models.IntegerField("數量")
    # 種類：登記時選的統計分組名稱（存文字，之後分組版本換了也不受影響）；空白是未分類
    kind = models.CharField("種類", max_length=50, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="操作人", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField("登記時間", auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="最後修改人", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField("最後修改時間", auto_now=True)

    objects = RecordQuerySet.as_manager()

    class Meta:
        verbose_name = "登記紀錄"
        verbose_name_plural = "登記紀錄"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.number} {self.name}"

    @property
    def edited(self):
        """登記後有人修改過（儲存時 updated_by 才會填）。"""
        return self.updated_by_id is not None
