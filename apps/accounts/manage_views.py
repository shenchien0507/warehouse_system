"""帳號與組織的後台管理頁。"""

from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import FormView, TemplateView, UpdateView

from apps.backoffice.menu import MENU
from apps.backoffice.views import ManageCreateView, ManageDeleteView, ManageListView, ManageMixin, ManageUpdateView

from .forms import (
    DepartmentForm, LevelForm, LevelRuleForm, PagePermissionForm, StationForm, UserCreateForm, UserPasswordForm, UserUpdateForm,
)
from .levels import RULES, RULES_BY_CODE, is_admin, levels_below
from .models import Department, Level, LevelRule, PagePermission, Station, User


class LevelMixin:
    model = Level
    form_class = LevelForm
    page_key = "manage-levels"
    list_url_name = "accounts_manage:level_list"


class LevelList(LevelMixin, ManageListView):
    """職級由管理員自訂：名稱、排序（數字越大越高）。權限依高低判斷，管理員是帳號身分不在這裡。"""

    columns = [
        ("職級", "name"),
        ("排序", "rank"),
        ("在職人員", lambda o: o.employee_count),
        ("啟用中的系統帳號", lambda o: o.user_count),
    ]
    create_url_name = "accounts_manage:level_create"
    edit_url_name = "accounts_manage:level_edit"
    delete_url_name = "accounts_manage:level_delete"

    def get_queryset(self):
        return Level.objects.annotate(
            employee_count=Count("employees", filter=Q(employees__is_active=True), distinct=True),
            user_count=Count("users", filter=Q(users__is_active=True), distinct=True),
        ).order_by("-rank")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["note"] = (
            "排序數字越大職級越高。頁面權限、職級規則都依高低判斷，非管理員只能管理比自己低的職級。"
            "還有人員、帳號或設定在用的職級不能刪除。管理員是系統帳號上的身分，不在這裡。"
        )
        return context


class LevelCreate(LevelMixin, ManageCreateView):
    pass


class LevelUpdate(LevelMixin, ManageUpdateView):
    pass


class LevelDelete(LevelMixin, ManageDeleteView):
    pass


class LevelRuleList(ManageMixin, TemplateView):
    """列出 levels.RULES 的每條規則與目前門檻。"""

    template_name = "backoffice/list.html"
    page_key = "manage-level-rules"
    list_url_name = "accounts_manage:level_rule_list"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        configured = {r.code: r for r in LevelRule.objects.select_related("min_level")}
        rows = []
        for rule in RULES:
            setting = configured.get(rule.code)
            level = setting.min_level if setting else None
            rows.append({
                "cells": [rule.label, f"{level}以上" if level else "只有管理員"],
                "actions": [("編輯", reverse("accounts_manage:level_rule_edit", args=[rule.code]), "primary")],
            })
        context["headers"] = ["規則", "可以的職級"]
        context["rows"] = rows
        context["note"] = "系統裡依職級判斷的操作，門檻在這裡設定。管理員不受限制。"
        return context


class LevelRuleUpdate(ManageMixin, UpdateView):
    template_name = "backoffice/form.html"
    form_class = LevelRuleForm
    page_key = "manage-level-rules"
    list_url_name = "accounts_manage:level_rule_list"

    def get_object(self, queryset=None):
        if self.kwargs["code"] not in RULES_BY_CODE:
            raise Http404
        return LevelRule.objects.get_or_create(code=self.kwargs["code"])[0]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object"] = RULES_BY_CODE[self.object.code].label
        return context

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "已儲存。")
        return redirect(self.get_success_url())


class DepartmentMixin:
    model = Department
    form_class = DepartmentForm
    page_key = "manage-departments"
    list_url_name = "accounts_manage:department_list"


class DepartmentList(DepartmentMixin, ManageListView):
    queryset = Department.objects.order_by("name")
    columns = [("部門名稱", "name")]
    search_fields = ["name"]
    create_url_name = "accounts_manage:department_create"
    edit_url_name = "accounts_manage:department_edit"
    delete_url_name = "accounts_manage:department_delete"


class DepartmentCreate(DepartmentMixin, ManageCreateView):
    pass


class DepartmentUpdate(DepartmentMixin, ManageUpdateView):
    pass


class DepartmentDelete(DepartmentMixin, ManageDeleteView):
    pass


class StationMixin:
    model = Station
    form_class = StationForm
    page_key = "manage-stations"
    list_url_name = "accounts_manage:station_list"


class StationList(StationMixin, ManageListView):
    queryset = Station.objects.order_by("name")
    columns = [("工位名稱", "name")]
    search_fields = ["name"]
    create_url_name = "accounts_manage:station_create"
    edit_url_name = "accounts_manage:station_edit"
    delete_url_name = "accounts_manage:station_delete"


class StationCreate(StationMixin, ManageCreateView):
    pass


class StationUpdate(StationMixin, ManageUpdateView):
    pass


class StationDelete(StationMixin, ManageDeleteView):
    pass


class UserMixin:
    """非管理員只能管理職級比自己低的帳號，也只能設定比自己低的職級。"""

    model = User
    page_key = "manage-users"
    list_url_name = "accounts_manage:user_list"

    def get_queryset(self):
        queryset = User.objects.select_related("department", "level").order_by("username")
        editor = self.request.user
        if not is_admin(editor):
            below = Q(level__in=levels_below(editor))
            if editor.level_id:
                below |= Q(level=None)
            queryset = queryset.filter(below, is_admin=False, is_superuser=False)
        return queryset

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["editor"] = self.request.user
        return kwargs


class UserList(UserMixin, ManageListView):
    columns = [
        ("工號", "username"),
        ("姓名", "name"),
        ("職級", "level_display"),
        ("部門", "department"),
        ("啟用", "is_active"),
        ("最後登入", lambda o: o.last_login.strftime("%Y-%m-%d %H:%M") if o.last_login else ""),
    ]
    search_fields = ["username", "name"]
    search_placeholder = "工號或姓名"
    create_url_name = "accounts_manage:user_create"
    edit_url_name = "accounts_manage:user_edit"


class UserCreate(UserMixin, ManageCreateView):
    """從人員資料按「開帳號」進來時，會帶 ?employee= 預先選好人員。"""

    form_class = UserCreateForm

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("employee", "").isdigit():
            initial["employee"] = self.request.GET["employee"]
        return initial


class UserUpdate(UserMixin, ManageUpdateView):
    form_class = UserUpdateForm
    template_name = "accounts/user_form.html"


class UserPassword(UserMixin, ManageMixin, FormView):
    """幫使用者重設密碼（忘記密碼時使用）。"""

    template_name = "backoffice/form.html"
    form_class = UserPasswordForm

    def get_target(self):
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    def get_form_kwargs(self):
        kwargs = FormView.get_form_kwargs(self)
        kwargs["user"] = self.get_target()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object"] = f"{context['form'].user}／重設密碼"
        return context

    def form_valid(self, form):
        form.save()
        messages.success(self.request, f"已重設 {form.user} 的密碼。")
        return redirect(reverse("accounts_manage:user_edit", args=[form.user.pk]))


class PagePermissionMixin:
    model = PagePermission
    form_class = PagePermissionForm
    page_key = "manage-page-permissions"
    list_url_name = "accounts_manage:page_permission_list"


class PagePermissionList(PagePermissionMixin, ManageMixin, TemplateView):
    """列出選單上所有可設定的頁面，沒設定過的顯示「未開放」（只有管理員能用）。"""

    template_name = "backoffice/list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        configured = {p.page_key: p for p in PagePermission.objects.select_related("min_level").prefetch_related("departments")}
        rows = []
        for item in MENU:
            if item.admin_only:
                continue
            permission = configured.get(item.page_key)
            if permission:
                rows.append({
                    "cells": [
                        item.group,
                        item.label,
                        f"{permission.min_level}以上",
                        "、".join(d.name for d in permission.departments.all()) or "全部部門",
                    ],
                    "actions": [
                        ("編輯", reverse("accounts_manage:page_permission_edit", args=[permission.pk]), "primary"),
                        ("刪除", reverse("accounts_manage:page_permission_delete", args=[permission.pk]), "danger"),
                    ],
                })
            else:
                rows.append({
                    "cells": [item.group, item.label, "未開放（只有管理員）", ""],
                    "actions": [("開放", f"{reverse('accounts_manage:page_permission_create')}?page={item.page_key}", "success")],
                })
        context["headers"] = ["分類", "頁面", "可使用職級", "開放部門"]
        context["rows"] = rows
        context["note"] = "「頁面權限」本身只有管理員能用，不在這裡設定。"
        return context


class PagePermissionCreate(PagePermissionMixin, ManageCreateView):
    success_message = "已開放。"

    def get_initial(self):
        initial = super().get_initial()
        initial["page_key"] = self.request.GET.get("page", "")
        return initial


class PagePermissionUpdate(PagePermissionMixin, ManageUpdateView):
    pass


class PagePermissionDelete(PagePermissionMixin, ManageDeleteView):
    """刪除設定就是關閉頁面：之後只有管理員能用。"""
