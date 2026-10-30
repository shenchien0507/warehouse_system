from django import forms

from .models import Record

FIELDS = ["number", "date_text", "name", "quantity"]


class RecordForm(forms.ModelForm):
    class Meta:
        model = Record
        fields = FIELDS
        error_messages = {"quantity": {"invalid": "數量只能輸入整數。"}}


class GridRowForm(RecordForm):
    """多列輸入的一列：整列空白就略過，不算錯誤。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.empty_permitted = True
        self.use_required_attribute = False
        for name, field in self.fields.items():
            field.widget.attrs.update({"class": "form-control form-control-sm", "data-col": name, "autocomplete": "off"})
        self.fields["quantity"].widget.attrs["inputmode"] = "numeric"


GridFormSet = forms.formset_factory(GridRowForm, extra=10, max_num=500, validate_max=True)
