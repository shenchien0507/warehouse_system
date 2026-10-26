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
