from django import forms

from apps.accounts.levels import is_admin, levels_below, outranks

from .models import Employee


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
        field.required = True
        field.help_text = "有系統帳號時，帳號職級會跟著這裡"
        self.fields["is_active"].help_text = "取消勾選（離職）時，系統帳號會一併停用"
        if is_admin(editor):
            return
        allowed = levels_below(editor)
        if self.instance.pk and (self.instance.user_id == editor.pk or not outranks(editor, self.instance.level)):
            field.queryset = field.queryset.filter(pk=self.instance.level_id)
            field.disabled = True
            field.help_text = "只能設定比自己低的職級"
        else:
            field.queryset = allowed
            if self.initial.get("level") not in set(allowed.values_list("pk", flat=True)):
                self.initial["level"] = allowed.order_by("rank").values_list("pk", flat=True).first()
