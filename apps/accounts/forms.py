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


class EmployeeChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj}（{obj.get_level_display()}）"


class UserCreateForm(UserCreationForm):
    """帳號一定要先有人員資料：工號、姓名、電話、部門、職級都取自人員資料，不在這裡另外填。
    要設成管理員，建立後再到帳號編輯修改。"""

    employee = EmployeeChoiceField(
        Employee.objects.none(),
        label="人員",
        help_text="職級依人員資料帶入。只列出在職、還沒有帳號、職級比你低的人員；找不到請先到「人員資料」新增或調整",
    )
    field_order = ["employee", "email", "is_active", "password1", "password2"]

    class Meta:
        model = User
        fields = ["email", "is_active"]

    def __init__(self, *args, editor, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Employee.objects.filter(is_active=True, user=None).order_by("employee_no")
        if editor.level != Level.ADMIN:
            queryset = queryset.filter(level__lt=editor.level)
        self.fields["employee"].queryset = queryset

    def clean_employee(self):
        employee = self.cleaned_data["employee"]
        if User.objects.filter(username__iexact=employee.employee_no).exists():
            raise forms.ValidationError("已經有相同工號的帳號。")
        return employee

    def save(self, commit=True):
        employee = self.cleaned_data["employee"]
        user = super().save(commit=False)
        user.username, user.name, user.phone, user.department, user.level = (
            employee.employee_no, employee.name, employee.phone, employee.department, employee.level,
        )
        if commit:
            with transaction.atomic():
                user.save()
                employee.user = user
                employee.save()
        return user


class UserUpdateForm(LevelLimitMixin, forms.ModelForm):
    """有人員資料的帳號，工號、姓名、電話、部門、職級要到人員資料修改；沒有人員資料的舊帳號（如管理員）可直接改。
    有人員資料的帳號，管理員可以在這裡改成「管理員」或改回人員資料的職級。"""

    class Meta:
        model = User
        fields = ["username", "name", "phone", "email", "level", "department", "is_active"]

    def __init__(self, *args, editor, **kwargs):
        super().__init__(*args, editor=editor, **kwargs)
        self.fields["username"].label = "工號"
        self.fields["username"].disabled = True
        if hasattr(self.instance, "employee"):
            for field in ("name", "phone", "department"):
                self.fields[field].disabled = True
                self.fields[field].help_text = "請到「人員資料」修改"
            level = self.fields["level"]
            if editor.level == Level.ADMIN:
                # 只能在人員資料的職級和管理員之間切換
                employee_level = self.instance.employee.level
                level.choices = [(value, label) for value, label in Level.choices if value in (employee_level, Level.ADMIN)]
                level.help_text = "職級請到「人員資料」修改；這裡只能設為管理員，或改回人員資料的職級"
            else:
                level.disabled = True
                level.help_text = "請到「人員資料」修改"


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
