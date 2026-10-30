"""當日統計：每個作業日是一個資料池，當天每個時段確定要出的訂單匯入成一批，一批一批累加上去（不覆蓋）。
同一作業日同一個訂單號只算一次，歸在第一次出現的批次；之後批次再出現的商品列照存，標記為重複。
後續功能從 DailyOrder（當天確定要出的訂單）和 DailyLine 引用、比對資料。欄位對應、統計分組和「訂單統計」共用。"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.orders.models import GroupVersion, MappingVersion


class DailyBatch(models.Model):
    """匯入一份檔案就是一批，屬於一個作業日，依匯入順序編號（第 1 批、第 2 批…）。"""

    work_date = models.DateField("作業日")
    seq = models.PositiveIntegerField("第幾批")
    file_name = models.CharField("檔名", max_length=200)
    file_hash = models.CharField("檔案指紋", max_length=64, blank=True)  # SHA-256，同作業日同內容的檔案不能再匯入
    imported_at = models.DateTimeField("匯入時間", auto_now_add=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="匯入人", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    mapping_version = models.ForeignKey(MappingVersion, verbose_name="欄位對應版本", on_delete=models.PROTECT, related_name="+")
    group_version = models.ForeignKey(GroupVersion, verbose_name="統計分組版本", on_delete=models.PROTECT, related_name="+")
    line_count = models.PositiveIntegerField("商品列數", default=0)
    order_count = models.PositiveIntegerField("訂單數", default=0)  # 檔案裡的訂單數（去重）
    new_order_count = models.PositiveIntegerField("新訂單數", default=0)  # 這批第一次出現、算進當日的訂單

    class Meta:
        verbose_name = "當日匯入批次"
        verbose_name_plural = "當日匯入批次"
        ordering = ["work_date", "seq"]
        constraints = [models.UniqueConstraint(fields=["work_date", "seq"], name="unique_daily_batch_seq")]

    def __str__(self):
        return f"{self.work_date:%Y/%m/%d} 第 {self.seq} 批"

    @property
    def duplicate_order_count(self):
        return self.order_count - self.new_order_count

    @property
    def referenced_later(self):
        """這批的訂單在其他批次被標成重複。"""
        return DailyLine.objects.filter(order__batch=self).exclude(batch=self).exists()

    @property
    def is_latest(self):
        return not DailyBatch.objects.filter(work_date=self.work_date, seq__gt=self.seq).exists()


class DailyOrder(models.Model):
    """當日資料池裡的一張訂單：同一作業日同一訂單號只有一筆，歸在第一次出現的批次。"""

    work_date = models.DateField("作業日")
    order_no = models.CharField("訂單號", max_length=100)
    batch = models.ForeignKey(DailyBatch, verbose_name="第一次出現的批次", on_delete=models.CASCADE, related_name="orders")

    class Meta:
        verbose_name = "當日訂單"
        verbose_name_plural = "當日訂單"
        ordering = ["work_date", "batch__seq", "order_no"]
        constraints = [models.UniqueConstraint(fields=["work_date", "order_no"], name="unique_daily_order")]

    def __str__(self):
        return f"{self.work_date:%Y/%m/%d} {self.order_no}"


class DailyLine(models.Model):
    """來源檔的一列（一個商品），欄位和訂單統計的 OrderLine 一樣。
    is_duplicate：這張訂單已在同一作業日更早的批次出現過，這列不算進當日統計。"""

    batch = models.ForeignKey(DailyBatch, verbose_name="匯入批次", on_delete=models.CASCADE, related_name="lines")
    order = models.ForeignKey(DailyOrder, verbose_name="當日訂單", on_delete=models.CASCADE, related_name="lines")
    is_duplicate = models.BooleanField("重複", default=False)
    row_no = models.PositiveIntegerField("來源檔第幾列")
    order_no = models.CharField("訂單號", max_length=100)
    platform_order_no = models.CharField("平台訂單編號", max_length=100, blank=True)
    platform = models.CharField("平台", max_length=100, blank=True)
    shop = models.CharField("店鋪", max_length=100, blank=True)
    order_time = models.DateTimeField("下單時間", null=True, blank=True)
    ship_time = models.DateTimeField("出貨時間", null=True, blank=True)
    ship_type = models.CharField("出貨方式", max_length=100, blank=True)
    shipment_no = models.CharField("出貨單號", max_length=100, blank=True)
    product_code = models.CharField("商品編號", max_length=100, blank=True)
    product_name = models.CharField("商品名稱", max_length=300, blank=True)
    product_spec = models.CharField("商品樣式", max_length=300, blank=True)
    quantity = models.IntegerField("數量", null=True, blank=True)

    class Meta:
        verbose_name = "當日商品列"
        verbose_name_plural = "當日商品列"
        indexes = [models.Index(fields=["batch", "order_no"])]

    def __str__(self):
        return f"{self.order_no} {self.product_code}"


class DailyHold(models.Model):
    """抽單：當日訂單有問題先抽起來，不算進當日統計，之後放回。一張訂單可以抽、放好幾次，每次一筆紀錄。
    放回有兩種：手動按「放回」，或之後匯入的批次檔裡又出現這張訂單（同一作業日自動放回；
    其他作業日的檔案出現，代表改到那天出，訂單算進那天，原本那天繼續不算）。"""

    HELD, RELEASED, RETURNED, MOVED = "held", "released", "returned", "moved"
    STATUS_CHOICES = [(HELD, "抽起中"), (RELEASED, "手動放回"), (RETURNED, "批次出現，自動放回"), (MOVED, "轉到其他作業日")]
    EXCLUDED = (HELD, MOVED)  # 原本那天不算的狀態

    order = models.ForeignKey(DailyOrder, verbose_name="當日訂單", on_delete=models.CASCADE, related_name="holds")
    reason = models.CharField("原因", max_length=200)
    status = models.CharField("狀態", max_length=10, choices=STATUS_CHOICES, default=HELD)
    held_at = models.DateTimeField("抽起時間", auto_now_add=True)
    held_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="抽起人", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    released_at = models.DateTimeField("放回時間", null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="放回人", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    released_batch = models.ForeignKey(
        DailyBatch, verbose_name="出現在哪一批", null=True, blank=True, on_delete=models.SET_NULL, related_name="released_holds"
    )

    class Meta:
        verbose_name = "抽單紀錄"
        verbose_name_plural = "抽單紀錄"
        ordering = ["-held_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["order"], condition=models.Q(status="held"), name="unique_daily_hold_held"),
        ]

    def __str__(self):
        return f"{self.order} {self.get_status_display()}"

    @property
    def is_held(self):
        return self.status == self.HELD

    @property
    def can_release(self):
        """手動放回只限作業日當天（含之前）；過了作業日要等之後的批次檔出現，自動轉到那天算，不改已經過去那天的數字。"""
        return self.is_held and timezone.localdate() <= self.order.work_date

    @property
    def outcome(self):
        """放回的說明，例如「第 3 批出現，自動放回」「轉到 10/31 第 1 批」。"""
        batch = self.released_batch
        if self.status == self.RETURNED and batch:
            return f"第 {batch.seq} 批出現，自動放回"
        if self.status == self.MOVED and batch:
            return f"轉到 {batch.work_date:%m/%d} 第 {batch.seq} 批"
        return self.get_status_display()

    def close(self, status, user, batch=None):
        self.status, self.released_by, self.released_batch = status, user, batch
        self.released_at = timezone.now()
        self.save(update_fields=["status", "released_by", "released_batch", "released_at"])
