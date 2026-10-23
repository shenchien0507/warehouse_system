from django import forms
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm
from django.db import transaction

from apps.backoffice.menu import MENU, MENU_BY_KEY
from apps.personnel.models import Employee

from .levels import is_admin, levels_below
from .models import RANK_MAX, RANK_MIN, Department, Level, LevelRule, PagePermission, Station, User


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name"]


class StationForm(forms.ModelForm):
    class Meta:
        model = Station
        fields = ["name"]


class LevelForm(forms.ModelForm):
    class Meta:
        model = Level
        fields = ["name", "rank"]
        widgets = {"rank": forms.NumberInput(attrs={"min": RANK_MIN, "max": RANK_MAX})}


class LevelRuleForm(forms.ModelForm):
    class Meta:
        model = LevelRule
        fields = ["min_level"]


class EmployeeChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj}（{obj.level or '未設定職級'}）"


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
        queryset = Employee.objects.filter(is_active=True, user=None).select_related("level").order_by("employee_no")
        if not is_admin(editor):
            queryset = queryset.filter(level__in=levels_below(editor))
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


class UserUpdateForm(forms.ModelForm):
    """有人員資料的帳號，工號、姓名、電話、部門、職級要到人員資料修改；沒有人員資料的舊帳號可直接改。
    「管理員」是帳號身分，只有管理員能設定，也不能取消自己的管理員。非管理員只能設比自己低的職級。"""

    class Meta:
        model = User
        fields = ["username", "name", "phone", "email", "level", "department", "is_admin", "is_active"]

    def __init__(self, *args, editor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "工號"
        self.fields["username"].disabled = True
        self.fields["level"].queryset = levels_below(editor)
        if not is_admin(editor) or self.instance.pk == editor.pk or self.instance.is_superuser:
            self.fields["is_admin"].disabled = True
        if hasattr(self.instance, "employee"):
            for field in ("name", "phone", "department", "level"):
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
        self.fields["min_level"].help_text = "這個職級以上可以使用；管理員不受限制"
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
