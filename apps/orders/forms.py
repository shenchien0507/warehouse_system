from django import forms
from django.utils import timezone

from apps.attendance.forms import TIME_FORMATS, time_input

from .fields import FIELDS, KIND_LABELS
from .models import GroupVersion, ImportCategory, MappingVersion, StatCondition, StatGroup


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
    """一次匯入：每個使用中的分類一個上傳格（可以只放幾個），加上共用的作業日。"""

    work_date = forms.DateField(
        label="作業日", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="統計算這一天的作業：作業日之前的訂單都算進切開時間前，作業日當天的才依時間分前後。預設今天。",
    )

    def __init__(self, *args, categories=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["work_date"].initial = timezone.localdate()
        self.categories = list(categories)
        for category in self.categories:
            self.fields[self.file_field(category)] = forms.FileField(label=category.name, required=False)

    @staticmethod
    def file_field(category):
        return f"file_{category.pk}"

    @property
    def file_fields(self):
        return [self[self.file_field(c)] for c in self.categories]

    def clean(self):
        cleaned = super().clean()
        if not self.categories:
            raise forms.ValidationError("後台還沒有使用中的匯入分類，請先到後台「匯入分類」設定。")
        if not any(cleaned.get(self.file_field(c)) for c in self.categories):
            raise forms.ValidationError("至少要放一份檔案。")
        return cleaned

    def files_to_import(self):
        """[(分類, 上傳檔)]，沒放檔案的分類略過。"""
        return [(c, self.cleaned_data[self.file_field(c)]) for c in self.categories if self.cleaned_data.get(self.file_field(c))]


class ImportCategoryForm(forms.ModelForm):
    class Meta:
        model = ImportCategory
        fields = ["name", "sort_order", "is_active"]


class GroupVersionForm(forms.Form):
    """新增分組版本：上傳來源檔，讀出平台、店鋪、出貨類型的組合當條件的選項。"""

    file = forms.FileField(
        label="來源檔", help_text="上傳 .xlsx 或 .csv，用目前生效的欄位對應讀出交易平台、交易店鋪、出貨類型，條件只能從檔案裡有的值選。",
    )
    note = forms.CharField(label="備註", max_length=200, required=False)


class SourceFileForm(forms.Form):
    file = forms.FileField(label="來源檔", help_text="重新上傳會換掉選項；已設定的條件值不會被刪掉。")


class StatGroupForm(forms.ModelForm):
    class Meta:
        model = StatGroup
        fields = ["name", "sort_order", "cutoff", "midnight_uses_import_time", "carry_over", "split_by_day", "show_rows"]
        widgets = {"cutoff": time_input()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cutoff"].input_formats = TIME_FORMATS


class StatConditionForm(forms.ModelForm):
    """一組條件：三個都可以勾多個，留空代表全部；選項來自版本的來源檔，畫面上依選到的平台、店鋪連動縮小範圍。"""

    platforms = forms.MultipleChoiceField(label="交易平台", required=False, widget=forms.CheckboxSelectMultiple)
    shops = forms.MultipleChoiceField(label="交易店鋪", required=False, widget=forms.CheckboxSelectMultiple)
    ship_types = forms.MultipleChoiceField(label="出貨類型", required=False, widget=forms.CheckboxSelectMultiple)

    CHOICE_FIELDS = ["platforms", "shops", "ship_types"]  # 順序同 GroupVersion.source_combos 的 [平台, 店鋪, 出貨類型]

    class Meta:
        model = StatCondition
        fields = ["platforms", "shops", "ship_types"]

    def __init__(self, *args, combos=(), **kwargs):
        super().__init__(*args, **kwargs)
        for i, name in enumerate(self.CHOICE_FIELDS):
            current = self.initial.get(name) or []
            values = sorted({c[i] for c in combos if c[i]} | set(current))  # 已選但來源檔沒有的值也保留
            self.fields[name].choices = [(v, v) for v in values]


class BaseConditionFormSet(forms.BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.conditions.exists():
            self.extra = 0  # 編輯已有條件的分組不自動多一組空白，要加再按「新增一組條件」

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["combos"] = self.instance.version.source_combos
        return kwargs

    def clean(self):
        super().clean()
        kept = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        filled = [f for f in kept if any(f.cleaned_data.get(n) for n in StatConditionForm.CHOICE_FIELDS)]
        if not filled:
            raise forms.ValidationError("至少要選一組條件（例如選一個交易平台）。")


ConditionFormSet = forms.inlineformset_factory(
    StatGroup, StatCondition, form=StatConditionForm, formset=BaseConditionFormSet, extra=1, can_delete=True,
)
