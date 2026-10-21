from django import forms

from .models import Employee, JobTitle


class JobTitleForm(forms.ModelForm):
    class Meta:
        model = JobTitle
        fields = ["name"]


class EmployeeForm(forms.ModelForm):
    """系統帳號不在這裡連結：要到「系統帳號」依人員資料建立。"""

    class Meta:
        model = Employee
        fields = ["employee_no", "name", "department", "job_title", "phone", "hire_date", "is_active", "note"]
        widgets = {
            "hire_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
