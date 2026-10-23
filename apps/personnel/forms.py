from django import forms

from apps.accounts.forms import allowed_levels
from apps.accounts.models import Level

from .models import EMPLOYEE_LEVEL_CHOICES, Employee


class EmployeeForm(forms.ModelForm):
    """系統帳號不在這裡連結：要到「系統帳號」依人員資料建立。

    職級會同步到帳號權限，所以和帳號一樣：非管理員只能設比自己低的職級，也不能改自己或職級不比自己低的人。"""

    class Meta:
        model = Employee
        fields = ["employee_no", "name", "level", "department", "phone", "hire_date", "note", "is_active"]
        widgets = {
            "hire_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, editor, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["level"]
        field.help_text = "有系統帳號時，帳號職級會跟著這裡"
        self.fields["is_active"].help_text = "取消勾選（離職）時，系統帳號會一併停用"
        if editor.level == Level.ADMIN:
            return
        current = self.instance.level if self.instance.pk else Level.STAFF
        allowed = allowed_levels(editor)
        if self.instance.user_id == editor.pk or current >= editor.level or not allowed:
            field.choices = [choice for choice in EMPLOYEE_LEVEL_CHOICES if choice[0] == current]
            field.disabled = True
            field.help_text = "只能設定比自己低的職級"
        else:
            field.choices = allowed
