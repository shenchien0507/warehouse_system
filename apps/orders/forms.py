from django import forms

from .fields import FIELDS, KIND_LABELS
from .models import MappingVersion


class UploadForm(forms.Form):
    """新增版本的第一步：上傳來源檔，讀出欄名當下拉選單的選項。"""

    file = forms.FileField(label="來源檔", help_text="上傳 .xlsx（讀第一個工作表）或 .csv，系統只讀欄名，不會存檔案內容。")
    header_row = MappingVersion._meta.get_field("header_row").formfield()


class MappingForm(forms.Form):
    """每個系統欄位一個下拉選單，選項是來源檔的欄名；同一個來源欄名只能選一次。"""

    note = forms.CharField(label="備註", max_length=200, required=False)

    def __init__(self, *args, version, **kwargs):
        super().__init__(*args, **kwargs)
        self.version = version
        mapped = version.mapping_dict()
        choices = [("", "— 不使用 —")] + [(c, c) for c in version.source_columns]
        self.fields["note"].initial = version.note
        for f in FIELDS:
            initial = mapped.get(f.key, "")
            self.fields[f.key] = forms.ChoiceField(
                label=f.label, required=f.must_map, choices=choices,
                initial=initial if initial in version.source_columns else "",
                widget=forms.Select(attrs={"class": "form-select source-column"}),
            )

    def mapping_rows(self):
        """給 template 用：[(系統欄位, 型態文字, 下拉選單)]"""
        return [(f, KIND_LABELS[f.kind], self[f.key]) for f in FIELDS]

    def clean(self):
        cleaned = super().clean()
        used = {}
        for f in FIELDS:
            source = cleaned.get(f.key)
            if not source:
                continue
            if source in used:
                self.add_error(f.key, f"「{source}」已經對應到「{used[source]}」，一個來源欄只能對應一個系統欄位。")
            else:
                used[source] = f.label
        return cleaned

    def save(self):
        self.version.note = self.cleaned_data["note"]
        self.version.save(update_fields=["note"])
        self.version.set_mappings({f.key: self.cleaned_data.get(f.key) for f in FIELDS})
        return self.version


class CheckFileForm(forms.Form):
    file = forms.FileField(label="來源檔", help_text="上傳 .xlsx 或 .csv，用這個版本試讀前 500 列，不會匯入任何訂單。")


class ImportForm(forms.Form):
    file = forms.FileField(label="訂單檔", help_text="上傳 .xlsx 或 .csv，用目前生效的欄位對應讀取；有任何一列錯誤就整份不匯入。")
