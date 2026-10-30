from django import forms

from .models import Record

FIELDS = ["number", "date_text", "name", "quantity"]


class RecordForm(forms.ModelForm):
    class Meta:
        model = Record
        fields = FIELDS
        error_messages = {"quantity": {"invalid": "數量只能輸入整數。"}}


class QuickAddForm(RecordForm):
    """列表上方固定的那一列：打完按登記就存一筆，輸入列清空給下一筆。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_required_attribute = False
        for name, field in self.fields.items():
            css = "form-control is-invalid" if self.errors.get(name) else "form-control"
            field.widget.attrs.update({"class": css, "data-quick": name, "autocomplete": "off"})
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
