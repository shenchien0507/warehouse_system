from django import forms
from django.utils import timezone

from apps.accounts.models import Station

from .models import ClockSetting, EventKind


def time_input():
    """24 小時制的時間欄位（瀏覽器內建的時間選擇器可能顯示上午／下午，所以用文字輸入 HH:MM）。"""
    return forms.TimeInput(
        format="%H:%M",
        attrs={"placeholder": "HH:MM", "pattern": r"([01]?\d|2[0-3]):[0-5]\d", "inputmode": "numeric", "maxlength": 5, "autocomplete": "off"},
    )


class EventForm(forms.Form):
    """補登一筆紀錄（上班、下班、請假、缺勤），可指定時間。"""

    kind = forms.ChoiceField(label="類型", choices=EventKind.choices)
    time = forms.TimeField(label="時間", required=False, input_formats=["%H:%M"], widget=time_input())
    end_time = forms.TimeField(label="請假到", required=False, input_formats=["%H:%M"], widget=time_input())
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
        label="當日工位", queryset=Station.objects.order_by("name"), required=False
    )


class ClockSettingForm(forms.ModelForm):
    class Meta:
        model = ClockSetting
        fields = ["work_start", "clock_in_early", "clock_in_late", "work_end", "clock_out_early", "clock_out_late"]
        widgets = {"work_start": time_input(), "work_end": time_input()}
        help_texts = {"work_start": "24 小時制，例如 08:00", "work_end": "24 小時制，例如 17:30"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("work_start", "work_end"):
            self.fields[name].input_formats = ["%H:%M"]
