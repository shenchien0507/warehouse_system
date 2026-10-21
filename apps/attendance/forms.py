from django import forms

from apps.accounts.models import Station

from .models import Status


class AttendanceRowForm(forms.Form):
    """登記表中一個人的一列。狀態留空代表未登記（已有紀錄會刪除）。"""

    status = forms.ChoiceField(label="狀態", choices=[("", "未登記")] + Status.choices, required=False)
    clock_in = forms.TimeField(label="上班時間", required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    clock_out = forms.TimeField(label="下班時間", required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    station = forms.ModelChoiceField(
        label="當日工位", queryset=Station.objects.select_related("department").order_by("department__name", "name"), required=False
    )
    note = forms.CharField(label="備註", max_length=200, required=False)

    def __init__(self, *args, editable=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not editable:
            for field in self.fields.values():
                field.disabled = True

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") != Status.PRESENT:
            # 沒到班就不記時間與工位
            cleaned["clock_in"] = cleaned["clock_out"] = cleaned["station"] = None
        return cleaned


class FilterForm(forms.Form):
    date = forms.DateField(label="日期", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    department = forms.ModelChoiceField(label="部門", queryset=None, empty_label=None)

    def __init__(self, *args, departments, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = departments
