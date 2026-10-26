from django import forms

from .fields import FIELDS, KIND_LABELS
from .models import FieldMapping, ImportTemplate


class ImportTemplateForm(forms.ModelForm):
    """範本基本資料，加上每個系統欄位一組「來源欄名」「必填」。"""

    class Meta:
        model = ImportTemplate
        fields = ["name", "header_row", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = {m.field: m for m in self.instance.mappings.all()} if self.instance.pk else {}
        self.mapping_rows = []
        for f in FIELDS:
            m = current.get(f.key)
            source = forms.CharField(
                label=f.label, max_length=100, required=f.always_required,
                initial=m.source_column if m else "",
                widget=forms.TextInput(attrs={"list": "known-columns", "autocomplete": "off", "placeholder": "不使用就留空"}),
            )
            self.fields[f"src_{f.key}"] = source
            if not f.always_required:
                self.fields[f"req_{f.key}"] = forms.BooleanField(label="必填", required=False, initial=bool(m and m.required))
            self.mapping_rows.append(f)

    def basic_fields(self):
        return [self[name] for name in self.Meta.fields]

    def mapping_fields(self):
        """給 template 用：[(系統欄位, 型態文字, 來源欄名欄位, 必填欄位或 None)]"""
        return [
            (f, KIND_LABELS[f.kind], self[f"src_{f.key}"], self[f"req_{f.key}"] if not f.always_required else None)
            for f in self.mapping_rows
        ]

    def clean(self):
        cleaned = super().clean()
        for f in self.mapping_rows:
            source = (cleaned.get(f"src_{f.key}") or "").strip()
            cleaned[f"src_{f.key}"] = source
            if not source and cleaned.get(f"req_{f.key}"):
                self.add_error(f"src_{f.key}", "設為必填就要填來源欄名。")
        return cleaned

    def save(self, commit=True):
        template = super().save(commit=True)
        for f in self.mapping_rows:
            source = self.cleaned_data[f"src_{f.key}"]
            if source:
                FieldMapping.objects.update_or_create(
                    template=template, field=f.key,
                    defaults={"source_column": source, "required": bool(self.cleaned_data.get(f"req_{f.key}"))},
                )
            else:
                FieldMapping.objects.filter(template=template, field=f.key).delete()
        return template


class TestFileForm(forms.Form):
    file = forms.FileField(label="來源檔", help_text="上傳 .xlsx 或 .csv。只讀第一個工作表，只檢查前 500 列，不會存入任何訂單。")
