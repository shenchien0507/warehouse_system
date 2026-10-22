from apps.backoffice.views import ManageCreateView, ManageDeleteView, ManageListView, ManageUpdateView

from .forms import EmployeeForm, JobTitleForm
from .models import Employee, JobTitle


class JobTitleMixin:
    model = JobTitle
    form_class = JobTitleForm
    page_key = "manage-job-titles"
    list_url_name = "personnel:job_title_list"


class JobTitleList(JobTitleMixin, ManageListView):
    columns = [("職務名稱", "name"), ("人數", lambda o: o.employees.filter(is_active=True).count())]
    search_fields = ["name"]
    create_url_name = "personnel:job_title_create"
    edit_url_name = "personnel:job_title_edit"
    delete_url_name = "personnel:job_title_delete"


class JobTitleCreate(JobTitleMixin, ManageCreateView):
    pass


class JobTitleUpdate(JobTitleMixin, ManageUpdateView):
    pass


class JobTitleDelete(JobTitleMixin, ManageDeleteView):
    pass


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
    queryset = Employee.objects.select_related("department", "job_title", "user")
    columns = [
        ("工號", "employee_no"),
        ("姓名", "name"),
        ("部門", "department"),
        ("職務", "job_title"),
        ("職級", "level"),
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status"] = self.request.GET.get("status", "active")
        return context


class EmployeeCreate(EmployeeMixin, ManageCreateView):
    pass


class EmployeeUpdate(EmployeeMixin, ManageUpdateView):
    pass
