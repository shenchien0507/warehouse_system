from django import forms
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm
from django.db import transaction

from apps.backoffice.menu import MENU, MENU_BY_KEY
from apps.personnel.models import Employee

from .models import Department, Level, PagePermission, Station, User


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name"]


class StationForm(forms.ModelForm):
    class Meta:
        model = Station
        fields = ["department", "name"]


def allowed_levels(editor):
    """管理員可設任何職級；其他人只能設比自己低的職級，避免把自己或別人升上來。"""
    if editor.level == Level.ADMIN:
        return Level.choices
    return [(value, label) for value, label in Level.choices if value < editor.level]


class LevelLimitMixin:
    def __init__(self, *args, editor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["level"].choices = allowed_levels(editor)


class UserCreateForm(LevelLimitMixin, UserCreationForm):
    """帳號一定要先有人員資料：工號、姓名、電話、部門都取自人員資料，不在這裡另外填。"""

    employee = forms.ModelChoiceField(
        Employee.objects.none(), label="人員", help_text="只列出在職、還沒有帳號的人員；找不到請先到「人員資料」新增"
    )

    class Meta:
        model = User
        fields = ["level", "email", "is_active"]
        field_order = ["employee", "level", "email", "is_active", "password1", "password2"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Employee.objects.filter(is_active=True, user=None).order_by("employee_no")

    def clean_employee(self):
        employee = self.cleaned_data["employee"]
        if User.objects.filter(username__iexact=employee.employee_no).exists():
            raise forms.ValidationError("已經有相同工號的帳號。")
        return employee

    def save(self, commit=True):
        employee = self.cleaned_data["employee"]
        user = super().save(commit=False)
        user.username, user.name, user.phone, user.department = (
            employee.employee_no, employee.name, employee.phone, employee.department,
        )
        if commit:
            with transaction.atomic():
                user.save()
                employee.user = user
                employee.save()
        return user


class UserUpdateForm(LevelLimitMixin, forms.ModelForm):
    """有人員資料的帳號，工號、姓名、電話、部門要到人員資料修改；沒有人員資料的舊帳號（如管理員）可直接改。"""

    class Meta:
        model = User
        fields = ["username", "name", "phone", "email", "level", "department", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "工號"
        self.fields["username"].disabled = True
        if hasattr(self.instance, "employee"):
            for field in ("name", "phone", "department"):
                self.fields[field].disabled = True
                self.fields[field].help_text = "請到「人員資料」修改"


class UserPasswordForm(SetPasswordForm):
    """管理者幫使用者重設密碼，不需要舊密碼。"""


class PagePermissionForm(forms.ModelForm):
    page_key = forms.ChoiceField(label="頁面")

    class Meta:
        model = PagePermission
        fields = ["page_key", "min_level", "departments"]
        widgets = {"departments": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["page_key"].choices = [(self.instance.page_key, self.instance.label)]
            self.fields["page_key"].disabled = True
        else:
            configured = set(PagePermission.objects.values_list("page_key", flat=True))
            self.fields["page_key"].choices = [
                (item.page_key, f"{item.group}／{item.label}") for item in MENU if item.page_key not in configured and not item.admin_only
            ]

    def save(self, commit=True):
        if not self.instance.pk:
            self.instance.label = MENU_BY_KEY[self.cleaned_data["page_key"]].label
        return super().save(commit)
