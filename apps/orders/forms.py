from django import forms

from apps.attendance.forms import TIME_FORMATS, time_input

from .fields import FIELDS, KIND_LABELS
from .models import GroupVersion, MappingVersion, OrderLine, StatCondition, StatGroup


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


class GroupVersionForm(forms.ModelForm):
    """新增空白的分組版本；要沿用現有分組請在版本頁按「複製成新版本」。"""

    class Meta:
        model = GroupVersion
        fields = ["note"]
        help_texts = {"note": "會建立沒有任何分組的空白草稿版本；要沿用現有分組，請到那個版本按「複製成新版本」。"}


class StatGroupForm(forms.ModelForm):
    class Meta:
        model = StatGroup
        fields = ["name", "sort_order", "cutoff", "midnight_uses_import_time", "show_rows"]
        widgets = {"cutoff": time_input()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cutoff"].input_formats = TIME_FORMATS


def seen_values(field):
    """匯入過的資料裡實際出現過的值，當條件的選項。"""
    return list(OrderLine.objects.exclude(**{field: ""}).order_by(field).values_list(field, flat=True).distinct())


class StatConditionForm(forms.ModelForm):
    """一組條件：三個都可以多選，留空代表全部；選項是匯入過的資料裡出現過的值。"""

    platforms = forms.MultipleChoiceField(label="交易平台", required=False)
    shops = forms.MultipleChoiceField(label="交易店鋪", required=False)
    ship_types = forms.MultipleChoiceField(label="出貨類型", required=False)

    CHOICE_FIELDS = {"platforms": "platform", "shops": "shop", "ship_types": "ship_type"}

    class Meta:
        model = StatCondition
        fields = ["platforms", "shops", "ship_types"]

    def __init__(self, *args, seen=None, **kwargs):
        super().__init__(*args, **kwargs)
        seen = seen or {}
        for name, source in self.CHOICE_FIELDS.items():
            current = self.initial.get(name) or []
            values = list(dict.fromkeys(list(seen.get(source, [])) + list(current)))  # 已選但資料裡沒有的值也保留
            self.fields[name].choices = [(v, v) for v in values]
            self.fields[name].widget.attrs.update({"class": "form-select", "size": 6})


class BaseConditionFormSet(forms.BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.seen = {source: seen_values(source) for source in StatConditionForm.CHOICE_FIELDS.values()}
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["seen"] = self.seen
        return kwargs

    def clean(self):
        super().clean()
        kept = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        filled = [f for f in kept if any(f.cleaned_data.get(n) for n in StatConditionForm.CHOICE_FIELDS)]
        if not filled:
            raise forms.ValidationError("至少要選一組條件（例如選一個交易平台）。")


ConditionFormSet = forms.inlineformset_factory(
    StatGroup, StatCondition, form=StatConditionForm, formset=BaseConditionFormSet, extra=2, can_delete=True,
)
