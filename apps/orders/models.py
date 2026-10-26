from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from .fields import FIELD_CHOICES, FIELDS


class MappingVersion(models.Model):
    """欄位對應的一個版本：每個系統欄位讀來源檔的哪一欄。

    同時只有一個版本生效（is_active）。生效過的版本（activated_at 有值）不能再改，要調整就複製成新版本。"""

    number = models.PositiveIntegerField("版本", unique=True)
    header_row = models.PositiveSmallIntegerField(
        "欄名在第幾列", default=1, validators=[MinValueValidator(1), MaxValueValidator(50)],
        help_text="欄名上面如果還有標題列，填欄名實際所在的列數。",
    )
    source_file_name = models.CharField("來源檔", max_length=200, blank=True)
    source_columns = models.JSONField("來源檔的欄名", default=list, blank=True)  # 下拉選單的選項
    note = models.CharField("備註", max_length=200, blank=True)
    is_active = models.BooleanField("生效中", default=False)
    activated_at = models.DateTimeField("第一次生效時間", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="建立人", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        verbose_name = "欄位對應版本"
        verbose_name_plural = "欄位對應版本"
        ordering = ["-number"]

    def __str__(self):
        return f"v{self.number}"

    @classmethod
    def next_number(cls):
        last = cls.objects.order_by("-number").values_list("number", flat=True).first()
        return (last or 0) + 1

    @classmethod
    def active(cls):
        return cls.objects.filter(is_active=True).first()

    @property
    def is_locked(self):
        return self.activated_at is not None

    @property
    def status(self):
        if self.is_active:
            return "生效中"
        return "已停用" if self.is_locked else "草稿"

    def mapping_dict(self):
        return {m.field: m.source_column for m in self.mappings.all()}

    def missing_must_map(self):
        """一定要對應、卻還沒選或選的欄名不在來源檔裡的系統欄位。"""
        mapped = self.mapping_dict()
        return [f for f in FIELDS if f.must_map and mapped.get(f.key) not in self.source_columns]

    def activate(self):
        with transaction.atomic():
            MappingVersion.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
            self.is_active = True
            self.activated_at = self.activated_at or timezone.now()
            self.save(update_fields=["is_active", "activated_at"])

    def copy(self, user):
        new = MappingVersion.objects.create(
            number=MappingVersion.next_number(), header_row=self.header_row, source_file_name=self.source_file_name,
            source_columns=self.source_columns, note=f"從 {self} 複製", created_by=user,
        )
        new.set_mappings(self.mapping_dict())
        return new

    def set_mappings(self, mapping):
        """mapping：{系統欄位 key: 來源欄名}，空白的不存。"""
        self.mappings.all().delete()
        ColumnMapping.objects.bulk_create(
            ColumnMapping(version=self, field=key, source_column=source) for key, source in mapping.items() if source
        )


class ColumnMapping(models.Model):
    """一個系統欄位對應一個來源欄名，同一版本裡來源欄名不能重複（一對一）。"""

    version = models.ForeignKey(MappingVersion, verbose_name="版本", on_delete=models.CASCADE, related_name="mappings")
    field = models.CharField("系統欄位", max_length=30, choices=FIELD_CHOICES)
    source_column = models.CharField("來源欄名", max_length=100)

    class Meta:
        verbose_name = "欄位對應"
        verbose_name_plural = "欄位對應"
        constraints = [
            models.UniqueConstraint(fields=["version", "field"], name="unique_version_field"),
            models.UniqueConstraint(fields=["version", "source_column"], name="unique_version_source_column"),
        ]

    def __str__(self):
        return f"{self.get_field_display()} ← {self.source_column}"


class ImportBatch(models.Model):
    """匯入一份檔案就是一批；訂單統計一批一批獨立計算，不同批之間不合併、不去重。"""

    file_name = models.CharField("檔名", max_length=200)
    imported_at = models.DateTimeField("匯入時間", auto_now_add=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="匯入人", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    mapping_version = models.ForeignKey(MappingVersion, verbose_name="欄位對應版本", on_delete=models.PROTECT, related_name="batches")
    line_count = models.PositiveIntegerField("商品列數", default=0)
    order_count = models.PositiveIntegerField("訂單數", default=0)

    class Meta:
        verbose_name = "匯入批次"
        verbose_name_plural = "匯入批次"
        ordering = ["-imported_at", "-pk"]

    def __str__(self):
        return f"#{self.pk} {self.file_name}"


class OrderLine(models.Model):
    """來源檔的一列（一個商品），欄位就是 fields.FIELDS，只存系統用得到的資料。"""

    batch = models.ForeignKey(ImportBatch, verbose_name="匯入批次", on_delete=models.CASCADE, related_name="lines")
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
        verbose_name = "訂單商品列"
        verbose_name_plural = "訂單商品列"
        indexes = [models.Index(fields=["batch", "order_no"])]

    def __str__(self):
        return f"{self.order_no} {self.product_code}"


class StatGroup(models.Model):
    """訂單統計的分組：符合任一條件的訂單算進這組；可設切開時間把一天分成前後兩個數字。"""

    name = models.CharField("分組名稱", max_length=50, unique=True)
    sort_order = models.PositiveIntegerField("顯示順序", default=0, help_text="數字小的排前面；同一張訂單符合多組時，算進排最前面的那組。")
    cutoff = models.TimeField(
        "切開時間", null=True, blank=True, help_text="例如 14:00；只看到分鐘，14:00 整（含 14:00:59）算前。留空就不分前後。"
    )
    midnight_uses_import_time = models.BooleanField(
        "下單時間是 00:00:00 時用匯入時間", default=False,
        help_text="有些平台只給日期（時間都是 00:00:00），勾選後這種訂單改用這批的匯入時間判斷前後；有實際時間的照下單時間。",
    )
    show_rows = models.BooleanField("另外列出非去重", default=False, help_text="非去重：有幾列就算幾張。")

    class Meta:
        verbose_name = "統計分組"
        verbose_name_plural = "統計分組"
        ordering = ["sort_order", "pk"]

    def __str__(self):
        return self.name


class StatCondition(models.Model):
    """分組的一組條件：平台、店鋪、出貨類型都要符合（空白代表全部）。"""

    group = models.ForeignKey(StatGroup, verbose_name="分組", on_delete=models.CASCADE, related_name="conditions")
    platforms = models.JSONField("交易平台", default=list, blank=True)
    shops = models.JSONField("交易店鋪", default=list, blank=True)
    ship_types = models.JSONField("出貨類型", default=list, blank=True)

    class Meta:
        verbose_name = "分組條件"
        verbose_name_plural = "分組條件"
        ordering = ["pk"]

    def matches(self, platform, shop, ship_type):
        return (
            (not self.platforms or platform in self.platforms)
            and (not self.shops or shop in self.shops)
            and (not self.ship_types or ship_type in self.ship_types)
        )

    def describe(self):
        parts = [
            (label, values) for label, values in
            [("平台", self.platforms), ("店鋪", self.shops), ("出貨類型", self.ship_types)] if values
        ]
        return "；".join(f"{label}：{'、'.join(values)}" for label, values in parts) or "全部訂單"
