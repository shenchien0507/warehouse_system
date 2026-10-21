"""帳號與組織的後台管理頁。"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import FormView

from apps.backoffice.views import ManageCreateView, ManageDeleteView, ManageListView, ManageMixin, ManageUpdateView

from .forms import DepartmentForm, PagePermissionForm, StationForm, UserCreateForm, UserPasswordForm, UserUpdateForm
from .models import Department, Level, PagePermission, Station, User


class DepartmentMixin:
    model = Department
    form_class = DepartmentForm
    page_key = "manage-departments"
    list_url_name = "accounts_manage:department_list"


class DepartmentList(DepartmentMixin, ManageListView):
    queryset = Department.objects.order_by("name")
    columns = [("部門名稱", "name"), ("工位數", lambda o: o.stations.count())]
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
    queryset = Station.objects.select_related("department").order_by("department__name", "name")
    columns = [("部門", "department"), ("工位名稱", "name")]
    search_fields = ["name", "department__name"]
    search_placeholder = "工位或部門"
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
    form_class = UserCreateForm


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


class PagePermissionList(PagePermissionMixin, ManageListView):
    queryset = PagePermission.objects.prefetch_related("departments").order_by("label")
    columns = [
        ("頁面", "label"),
        ("最低職級", "min_level"),
        ("開放部門", lambda o: "、".join(d.name for d in o.departments.all()) or "全部部門"),
    ]
    create_url_name = "accounts_manage:page_permission_create"
    edit_url_name = "accounts_manage:page_permission_edit"
    delete_url_name = "accounts_manage:page_permission_delete"


class PagePermissionCreate(PagePermissionMixin, ManageCreateView):
    pass


class PagePermissionUpdate(PagePermissionMixin, ManageUpdateView):
    pass


class PagePermissionDelete(PagePermissionMixin, ManageDeleteView):
    pass
