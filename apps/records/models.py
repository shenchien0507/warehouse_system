"""登記紀錄：單純打什麼記什麼的表格，暫時不和其他資料表關聯（之後的功能確定後再考慮）。
編號不能重複；日期存成純文字，輸入什麼就存什麼，不轉換、不檢查格式；操作人取自登入的帳號。"""

from django.conf import settings
from django.db import models


class Record(models.Model):
    number = models.CharField("編號", max_length=50, unique=True, error_messages={"unique": "這個編號已經登記過了。"})
    date_text = models.CharField("日期", max_length=50, blank=True)
    name = models.CharField("名稱", max_length=200)
    quantity = models.IntegerField("數量")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="操作人", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField("登記時間", auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="最後修改人", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField("最後修改時間", auto_now=True)

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
