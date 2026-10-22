from django import forms
from django.utils import timezone

from apps.accounts.models import Station

from .models import EventKind


class EventForm(forms.Form):
    """補登一筆紀錄（上班、下班、請假離開、請假、缺勤），可指定時間。"""

    kind = forms.ChoiceField(label="類型", choices=EventKind.choices)
    time = forms.TimeField(label="時間", required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    end_time = forms.TimeField(label="請假到", required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    note = forms.CharField(label="原因／備註", max_length=200, required=False)

    def clean(self):
        cleaned = super().clean()
        kind, start, end = cleaned.get("kind"), cleaned.get("time"), cleaned.get("end_time")
        if kind == EventKind.LEAVE:
            if start and end and end <= start:
                self.add_error("end_time", "結束時間要晚於開始時間。")
        else:
            cleaned["end_time"] = None
            if kind == EventKind.ABSENT:
                cleaned["time"] = None
            elif kind and not start:
                self.add_error("time", "請填時間。")
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
