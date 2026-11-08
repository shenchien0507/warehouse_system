"""日結：主任以上按「日結」結束一個作業日，存一份當下的數字（每個種類的應出、已出、待印、待撿、待包），
之後就換到下一個作業日。沒做完的（待印、待撿、待包）就是下一個作業日的「昨日未完成」。
後台「撿貨配貨設定」的結轉起算日沒填時，不用日結，作業日就是系統日期。"""

from django.conf import settings
from django.db import models


class DayClose(models.Model):
    work_date = models.DateField("作業日", unique=True)
    closed_at = models.DateTimeField("日結時間", auto_now_add=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="日結人", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # {"kinds": [{"name", "today", "carried", "done", "unprinted", "picking", "packing"}, ...]}
    # today = 當天當日統計匯入的量；carried = 開工時從前面轉來的；done = 當天配貨完成；
    # unprinted / picking / packing = 日結當下的待印、待撿、待包（轉到下一個作業日）
    snapshot = models.JSONField("日結數字", default=dict)

    class Meta:
        verbose_name = "日結"
        verbose_name_plural = "日結"
        ordering = ["-work_date"]

    def __str__(self):
        return f"{self.work_date:%Y/%m/%d} 日結"

    @property
    def kinds(self):
        return self.snapshot.get("kinds", [])

    @property
    def carry_total(self):
        """轉到下一個作業日的合計（待印＋待撿＋待包）。"""
        return sum(k.get("unprinted", 0) + k.get("picking", 0) + k.get("packing", 0) for k in self.kinds)

    def kind(self, name):
        return next((k for k in self.kinds if k["name"] == name), None)
