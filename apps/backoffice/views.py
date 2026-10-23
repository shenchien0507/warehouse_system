"""後台共用 view：各 app 的管理頁繼承這些類別，只要設定 model、form、欄位即可。"""

from django.contrib import messages
from django.forms import Form
from django.core.exceptions import PermissionDenied
from django.db.models import ProtectedError, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .menu import MENU_BY_KEY, accessible_menu, can_use


def menu_groups(user):
    """後台首頁與左側選單用：{群組: [頁面]}。"""
    groups = {}
    for item in accessible_menu(user, "backoffice"):
        groups.setdefault(item.group, []).append(item)
    return groups


def dashboard(request):
    groups = menu_groups(request.user)
    if not groups:
        raise PermissionDenied
    return render(request, "backoffice/dashboard.html", {"groups": groups, "menu_groups": groups})


class ManageMixin:
    """page_key 對應 menu.MENU；list_url_name 為列表頁的 url name。"""

    page_key = None
    list_url_name = None
    edit_url_name = None
    delete_url_name = None
    create_url_name = None

    def dispatch(self, request, *args, **kwargs):
        if not can_use(request.user, MENU_BY_KEY[self.page_key]):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    @property
    def menu_item(self):
        return MENU_BY_KEY[self.page_key]

    def get_success_url(self):
        return reverse(self.list_url_name)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_item"] = self.menu_item
        context["menu_groups"] = menu_groups(self.request.user)
        context["list_url"] = reverse(self.list_url_name)
        return context


class ManageListView(ManageMixin, ListView):
    """columns：[(標題, 屬性名稱或函式)]；search_fields：搜尋框比對的欄位。"""

    template_name = "backoffice/list.html"
    paginate_by = 20
    columns = []
    search_fields = []
    search_placeholder = "搜尋"

    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get("q", "").strip()
        if q and self.search_fields:
            condition = Q()
            for field in self.search_fields:
                condition |= Q(**{f"{field}__icontains": q})
            queryset = queryset.filter(condition)
        return queryset

    def cell(self, obj, column):
        value = column(obj) if callable(column) else getattr(obj, f"get_{column}_display", None)
        if value is None:
            value = getattr(obj, column)
        elif callable(value):
            value = value()
        if isinstance(value, bool):
            return "是" if value else "否"
        return "" if value is None else value

    def row_actions(self, obj):
        """每列右側的按鈕：[(文字, 網址, 樣式)]，樣式為 Bootstrap 的 btn-outline-* 顏色。"""
        actions = []
        if self.edit_url_name:
            actions.append(("編輯", reverse(self.edit_url_name, args=[obj.pk]), "primary"))
        if self.delete_url_name:
            actions.append(("刪除", reverse(self.delete_url_name, args=[obj.pk]), "danger"))
        return actions

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["headers"] = [label for label, _ in self.columns]
        context["rows"] = [
            {"cells": [self.cell(obj, column) for _, column in self.columns], "actions": self.row_actions(obj)}
            for obj in context["object_list"]
        ]
        context["create_url"] = reverse(self.create_url_name) if self.create_url_name else None
        context["q"] = self.request.GET.get("q", "")
        context["search_enabled"] = bool(self.search_fields)
        context["search_placeholder"] = self.search_placeholder
        return context


class ManageFormMixin(ManageMixin):
    template_name = "backoffice/form.html"
    success_message = "已儲存。"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return response


class ManageCreateView(ManageFormMixin, CreateView):
    success_message = "已新增。"


class ManageUpdateView(ManageFormMixin, UpdateView):
    pass


class ManageDeleteView(ManageMixin, DeleteView):
    template_name = "backoffice/confirm_delete.html"

    def get_form_class(self):
        # 各頁的 Mixin 會設定編輯用的 form_class，刪除只需要空白表單
        return Form

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, f"「{self.object}」還有其他資料在使用，不能刪除。")
            return redirect(self.get_success_url())
        messages.success(self.request, f"已刪除「{self.object}」。")
        return response
