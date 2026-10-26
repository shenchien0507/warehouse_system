from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .fields import FIELD_CHOICES, FIELDS_BY_KEY


class ImportTemplate(models.Model):
    """一種來源檔的格式，例如「蝦皮匯出」；每個系統欄位要讀來源檔的哪一欄記在 FieldMapping。"""

    name = models.CharField("範本名稱", max_length=50, unique=True)
    header_row = models.PositiveSmallIntegerField(
        "欄名在第幾列", default=1, validators=[MinValueValidator(1), MaxValueValidator(50)],
        help_text="欄名上面如果還有標題列，填欄名實際所在的列數。",
    )
    note = models.CharField("備註", max_length=200, blank=True)
    known_columns = models.JSONField("最近測試檔的欄名", default=list, blank=True)  # 編輯對應時當作選項
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        verbose_name = "匯入範本"
        verbose_name_plural = "匯入範本"
        ordering = ["name"]

    def __str__(self):
        return self.name


class FieldMapping(models.Model):
    template = models.ForeignKey(ImportTemplate, verbose_name="範本", on_delete=models.CASCADE, related_name="mappings")
    field = models.CharField("系統欄位", max_length=30, choices=FIELD_CHOICES)
    source_column = models.CharField("來源欄名", max_length=100)
    required = models.BooleanField("必填", default=False)

    class Meta:
        verbose_name = "欄位對應"
        verbose_name_plural = "欄位對應"
        constraints = [models.UniqueConstraint(fields=["template", "field"], name="unique_template_field")]

    def __str__(self):
        return f"{self.get_field_display()} ← {self.source_column}"

    @property
    def is_required(self):
        return self.required or FIELDS_BY_KEY[self.field].always_required
