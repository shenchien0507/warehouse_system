from django import forms
from django.utils import timezone

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
        # 工位在「工位安排」頁設定，登記頁只顯示
        self.fields["station"].disabled = True
        if not editable:
            for field in self.fields.values():
                field.disabled = True

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") != Status.PRESENT:
            # 沒到班就不記時間與工位
            cleaned["clock_in"] = cleaned["clock_out"] = cleaned["station"] = None
        return cleaned


class LookupForm(forms.Form):
    """到班登記：輸入工號查詢人員；日期預設今天。"""

    employee_no = forms.CharField(label="工號", max_length=30, required=False)
    date = forms.DateField(label="日期", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def clean_employee_no(self):
        return self.cleaned_data["employee_no"].strip()

    def clean_date(self):
        return self.cleaned_data["date"] or timezone.localdate()


class DateForm(forms.Form):
    date = forms.DateField(label="日期", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))


class StationAssignForm(forms.Form):
    """工位安排表中一個到班人員的一列。"""

    station = forms.ModelChoiceField(
        label="當日工位", queryset=Station.objects.select_related("department").order_by("department__name", "name"), required=False
    )
