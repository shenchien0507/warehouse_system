from django.urls import reverse

from apps.accounts.levels import outranks
from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.backoffice.views import ManageCreateView, ManageListView, ManageUpdateView

from .forms import EmployeeForm
from .models import Employee


class EmployeeMixin:
    model = Employee
    form_class = EmployeeForm
    page_key = "manage-employees"
    list_url_name = "personnel:employee_list"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["editor"] = self.request.user
        return kwargs


class EmployeeList(EmployeeMixin, ManageListView):
    template_name = "personnel/employee_list.html"
    queryset = Employee.objects.select_related("department", "level", "user")
    columns = [
        ("工號", "employee_no"),
        ("姓名", "name"),
        ("職級", "level"),
        ("部門", "department"),
        ("聯絡資料", "phone"),
        ("到職日", "hire_date"),
        ("在職", "is_active"),
        ("系統帳號", lambda o: o.user.username if o.user else ""),
    ]
    search_fields = ["employee_no", "name"]
    search_placeholder = "工號或姓名"
    create_url_name = "personnel:employee_create"
    edit_url_name = "personnel:employee_edit"

    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get("status", "active")
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        return queryset

    def row_actions(self, obj):
        # 在職、還沒有帳號、職級比自己低（管理員不限）的人，可以直接開帳號
        actions = super().row_actions(obj)
        user = self.request.user
        if not hasattr(self, "_can_create_account"):
            self._can_create_account = can_use(user, MENU_BY_KEY["manage-users"])
        if (
            self._can_create_account
            and obj.is_active
            and not obj.user_id
            and outranks(user, obj.level)
        ):
            actions.append(("開帳號", f"{reverse('accounts_manage:user_create')}?employee={obj.pk}", "success"))
        return actions

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status"] = self.request.GET.get("status", "active")
        return context


class EmployeeCreate(EmployeeMixin, ManageCreateView):
    pass


class EmployeeUpdate(EmployeeMixin, ManageUpdateView):
    pass
