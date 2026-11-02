from django import forms
from django.core.exceptions import ValidationError

from .models import WorkEntry
from .rules import check_cycle, check_number, check_rescan, find_employee, open_entry


def text_input(**attrs):
    return forms.TextInput(attrs={"class": "form-control", "autocomplete": "off", **attrs})


class ScanForm(forms.Form):
    """頁面上固定的那一列：編號、員工編號手動輸入（或刷條碼），時間由系統記。"""

    number = forms.CharField(label="編號", max_length=50, widget=text_input(autofocus=True, **{"data-scan": "number"}))
    employee_no = forms.CharField(label="員工編號", max_length=30, widget=text_input(**{"data-scan": "employee"}))

    def __init__(self, *args, stage, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage = stage

    def clean_number(self):
        number = check_number(self.stage, self.cleaned_data["number"].strip())
        check_rescan(self.stage, number)
        check_cycle(self.stage, number)
        return number

    def clean_employee_no(self):
        self.employee = find_employee(self.cleaned_data["employee_no"].strip())
        return self.employee.employee_no


class EntryEditForm(forms.ModelForm):
    """可以改編號和員工編號；開始、結束時間是系統記的，不能改。"""

    start_employee_no = forms.CharField(label="開始員工編號", max_length=30, widget=text_input())
    end_employee_no = forms.CharField(label="結束員工編號", max_length=30, widget=text_input())

    class Meta:
        model = WorkEntry
        fields = ["number"]
        widgets = {"number": text_input()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_employee_no"].initial = self.instance.start_employee.employee_no
        if self.instance.is_open:
            del self.fields["end_employee_no"]
        else:
            self.fields["end_employee_no"].initial = self.instance.end_employee.employee_no

    def clean_number(self):
        number = self.cleaned_data["number"].strip()
        if number != self.instance.number:
            number = check_number(self.instance.stage, number)
            if self.instance.is_open and open_entry(self.instance.stage, number, exclude=self.instance):
                raise ValidationError(f"編號「{number}」已經有一筆還沒結束的登記。")
        return number

    def employee_field(self, name, attr):
        """沒改就不重新比對（原本的人之後離職也能存）；改了要對得到在職的人員。"""
        employee_no = self.cleaned_data[name].strip()
        if employee_no != getattr(self.instance, attr).employee_no:
            setattr(self.instance, attr, find_employee(employee_no))
        return employee_no

    def clean_start_employee_no(self):
        return self.employee_field("start_employee_no", "start_employee")

    def clean_end_employee_no(self):
        return self.employee_field("end_employee_no", "end_employee")
