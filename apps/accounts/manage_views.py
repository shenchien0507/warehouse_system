"""帳號與組織的後台管理頁。"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.db.models import Count
from django.views.generic import FormView, TemplateView

from apps.backoffice.menu import MENU
from apps.backoffice.views import ManageCreateView, ManageDeleteView, ManageListView, ManageMixin, ManageUpdateView

from .forms import DepartmentForm, PagePermissionForm, StationForm, UserCreateForm, UserPasswordForm, UserUpdateForm
from apps.personnel.models import Employee

from .models import Department, Level, PagePermission, Station, User


class LevelList(ManageMixin, TemplateView):
    """職級是固定的五級（權限依職級高低判斷），這裡只列出各職級的人數，職級要到人員資料設定。"""

    template_name = "backoffice/list.html"
    page_key = "manage-levels"
    list_url_name = "accounts_manage:level_list"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        employees = dict(
            Employee.objects.filter(is_active=True).values_list("level").annotate(n=Count("pk")).values_list("level", "n")
        )
        users = dict(User.objects.filter(is_active=True).values_list("level").annotate(n=Count("pk")).values_list("level", "n"))
        context["headers"] = ["職級", "在職人員", "啟用中的系統帳號"]
        context["rows"] = [
            {"cells": [label, "—" if value == Level.ADMIN else employees.get(value, 0), users.get(value, 0)], "actions": []}
            for value, label in sorted(Level.choices, reverse=True)
        ]
        context["note"] = "職級固定為以上五級，頁面權限依職級高低判斷。人員的職級請到「人員資料」設定；管理員只在系統帳號設定。"
        return context


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
        queryset = User.objects.select_related("department").order_by("username")
        if self.request.user.level != Level.ADMIN:
            queryset = queryset.filter(level__lt=self.request.user.level, is_superuser=False)
        return queryset

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["editor"] = self.request.user
        return kwargs


class UserList(UserMixin, ManageListView):
    columns = [
        ("工號", "username"),
        ("姓名", "name"),
        ("職級", "level"),
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
        context["object"] = f"{kwargs['form'].user}／重設密碼"
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
        configured = {p.page_key: p for p in PagePermission.objects.prefetch_related("departments")}
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
                        permission.get_min_level_display() + "以上",
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
