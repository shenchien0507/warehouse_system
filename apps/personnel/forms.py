from django import forms

from apps.accounts.models import User

from .models import Employee, JobTitle


class JobTitleForm(forms.ModelForm):
    class Meta:
        model = JobTitle
        fields = ["name"]


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ["employee_no", "name", "department", "job_title", "phone", "hire_date", "is_active", "user", "note"]
        widgets = {
            "hire_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 只列出還沒連結到其他人員的帳號
        linked = Employee.objects.exclude(pk=self.instance.pk).exclude(user=None).values("user")
        self.fields["user"].queryset = User.objects.exclude(pk__in=linked).order_by("username")
