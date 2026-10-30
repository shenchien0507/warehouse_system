from django import forms

from .models import Record
from .rules import LINKED_NOTE, is_linked, kind_names

FIELDS = ["number", "date_text", "name", "quantity"]


def kind_choices(current=""):
    """種類選單：未分類加上生效版本的分組；舊紀錄的種類已不在清單時也留著，修改時不會被洗掉。"""
    names = kind_names()
    if current and current not in names:
        names.append(current)
    return [("", "未分類"), *[(name, name) for name in names]]


class RecordForm(forms.ModelForm):
    class Meta:
        model = Record
        fields = FIELDS
        error_messages = {"quantity": {"invalid": "數量只能輸入整數。"}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if is_linked(self.instance):  # 撿貨、配貨已經用這個編號登記過，編號不能再改
            number = self.fields["number"]
            number.disabled = True
            number.help_text = f"{LINKED_NOTE}，編號不能修改。"


class KindRecordForm(RecordForm):
    """多一個「種類」的單筆表單（列表上方固定輸入列、修改頁）。"""

    kind = forms.ChoiceField(label="種類", required=False)
    field_order = ["kind", *FIELDS]

    class Meta(RecordForm.Meta):
        fields = ["kind", *FIELDS]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = kind_choices(self.instance.kind)


class QuickAddForm(KindRecordForm):
    """列表上方固定的那一列：打完按登記就存一筆，輸入列清空給下一筆。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_required_attribute = False
        if kind_names():  # 新登記一定要先選種類（還沒設定統計分組時才不擋）
            kind = self.fields["kind"]
            kind.required = True
            kind.choices = [("", "請先選種類"), *kind.choices[1:]]
            kind.error_messages["required"] = "請先選種類。"
        for name, field in self.fields.items():
            css = "form-select" if name == "kind" else "form-control"
            if self.errors.get(name):
                css += " is-invalid"
            field.widget.attrs.update({"class": css, "autocomplete": "off"})
            if name != "kind":
                field.widget.attrs["data-quick"] = name
        self.fields["kind"].widget.attrs["data-kind-select"] = True
        self.fields["number"].widget.attrs["autofocus"] = True
        self.fields["quantity"].widget.attrs["inputmode"] = "numeric"


class GridRowForm(RecordForm):
    """多列輸入的一列：整列空白就略過，不算錯誤。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.empty_permitted = True
        self.use_required_attribute = False
        for name, field in self.fields.items():
            field.widget.attrs.update({"class": "form-control form-control-sm", "data-col": name, "autocomplete": "off"})
        self.fields["quantity"].widget.attrs["inputmode"] = "numeric"


class BaseGridFormSet(forms.BaseFormSet):
    def clean(self):
        """同一次輸入裡編號重複的列標紅（和已登記的重複由欄位本身檢查）；有錯的列會讓整批不存。"""
        seen = {}
        for row, form in enumerate(self.forms, start=1):
            number = getattr(form, "cleaned_data", {}).get("number")
            if not number:
                continue
            if number in seen:
                form.add_error("number", f"和第 {seen[number]} 列的編號重複。")
            else:
                seen[number] = row


GridFormSet = forms.formset_factory(GridRowForm, formset=BaseGridFormSet, extra=10, max_num=500, validate_max=True)

# 批量修改：勾選的紀錄一列一列列出來改，不能加列；同一批編號重複由 model formset 本身檢查
BulkEditFormSet = forms.modelformset_factory(Record, form=GridRowForm, extra=0, max_num=500, validate_max=True)
