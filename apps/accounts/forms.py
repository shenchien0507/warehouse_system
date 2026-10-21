from django import forms
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm

from apps.backoffice.menu import MENU, MENU_BY_KEY

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
        self.fields["username"].label = "工號"


USER_FIELDS = ["username", "name", "phone", "email", "level", "department", "station", "is_active"]


class UserCreateForm(LevelLimitMixin, UserCreationForm):
    class Meta:
        model = User
        fields = USER_FIELDS


class UserUpdateForm(LevelLimitMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = USER_FIELDS


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
