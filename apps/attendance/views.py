from collections import Counter

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView

from apps.accounts.models import Level
from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.personnel.models import Employee

from .forms import AttendanceRowForm, FilterForm, StationAssignForm
from .models import Attendance, Status
from .rules import can_arrange, can_edit, departments_in_scope, station_departments


class AttendanceMixin:
    page_key = None

    def get_departments(self, user):
        return departments_in_scope(user)

    def dispatch(self, request, *args, **kwargs):
        self.departments = self.get_departments(request.user)
        if not can_use(request.user, MENU_BY_KEY[self.page_key]):
            raise PermissionDenied
        if not self.departments.exists():
            if request.user.level >= Level.MANAGER:
                messages.warning(request, "還沒有建立任何部門，請先到「部門」新增。")
            else:
                messages.warning(request, "你的帳號沒有設定部門，或職級不足，不能使用這個功能。")
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def get_filter(self):
        defaults = {"date": timezone.localdate(), "department": self.departments.first().pk}
        form = FilterForm({key: self.request.GET.get(key) or value for key, value in defaults.items()}, departments=self.departments)
        if not form.is_valid():
            # 參數不正確（或部門不在可登記範圍）就回到今天、第一個部門
            form = FilterForm(defaults, departments=self.departments)
            form.is_valid()
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_item"] = MENU_BY_KEY[self.page_key]
        return context


class RegisterView(AttendanceMixin, TemplateView):
    """依日期與部門整批登記到班。"""

    page_key = "attendance-register"
    template_name = "attendance/register.html"

    def build_rows(self, date, department, data=None):
        records = {r.employee_id: r for r in Attendance.objects.filter(date=date, employee__department=department).select_related("created_by")}
        employees = (
            Employee.objects.filter(department=department)
            .filter(is_active=True) | Employee.objects.filter(pk__in=records.keys())
        ).select_related("job_title").distinct().order_by("employee_no")
        rows = []
        for employee in employees:
            record = records.get(employee.pk)
            editable = can_edit(self.request.user, date, record)
            initial = {}
            if record:
                initial = {f: getattr(record, f) for f in ("status", "clock_in", "clock_out", "station", "note")}
            form = AttendanceRowForm(data, prefix=f"e{employee.pk}", initial=initial, editable=editable)
            rows.append({"employee": employee, "record": record, "form": form, "editable": editable})
        return rows

    def get(self, request, *args, **kwargs):
        self.filter = self.get_filter()
        cd = self.filter.cleaned_data
        return self.render_to_response(self.get_context_data(rows=self.build_rows(cd["date"], cd["department"])))

    def post(self, request, *args, **kwargs):
        self.filter = self.get_filter()
        cd = self.filter.cleaned_data
        rows = self.build_rows(cd["date"], cd["department"], data=request.POST)
        editable_rows = [row for row in rows if row["editable"]]
        if not all(row["form"].is_valid() for row in editable_rows):
            messages.error(request, "有欄位格式不正確，請檢查標紅的地方。")
            return self.render_to_response(self.get_context_data(rows=rows))
        saved = 0
        with transaction.atomic():
            for row in editable_rows:
                form, record = row["form"], row["record"]
                if not form.has_changed():
                    continue
                values = form.cleaned_data
                if not values["status"]:
                    if record:
                        record.delete()
                        saved += 1
                    continue
                if record is None:
                    record = Attendance(employee=row["employee"], date=cd["date"], created_by=request.user)
                for field in ("status", "clock_in", "clock_out", "station", "note"):
                    setattr(record, field, values[field])
                record.updated_by = request.user
                record.save()
                saved += 1
        messages.success(request, f"已儲存 {saved} 筆。" if saved else "沒有變更。")
        return redirect(f"{request.path}?date={cd['date']:%Y-%m-%d}&department={cd['department'].pk}")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter"] = self.filter
        context["date"] = self.filter.cleaned_data["date"]
        context["is_today"] = context["date"] == timezone.localdate()
        context["any_editable"] = any(row["editable"] for row in context["rows"])
        return context


class StationAssignView(AttendanceMixin, TemplateView):
    """到班登記完成後，依日期與部門安排到班人員的當日工位。改完先列出變更，確認後才批次儲存。"""

    page_key = "attendance-stations"
    template_name = "attendance/stations.html"

    def get_departments(self, user):
        return station_departments(user)

    def build_rows(self, date, department, data=None):
        records = (
            Attendance.objects.filter(date=date, employee__department=department, status=Status.PRESENT)
            .select_related("employee__job_title", "station__department")
            .order_by("employee__employee_no")
        )
        editable = can_arrange(self.request.user, date)
        rows = []
        for record in records:
            form = StationAssignForm(data, prefix=f"a{record.pk}", initial={"station": record.station})
            if not editable:
                form.fields["station"].disabled = True
            rows.append({"record": record, "form": form})
        return rows, editable

    def get(self, request, *args, **kwargs):
        self.filter = self.get_filter()
        cd = self.filter.cleaned_data
        rows, editable = self.build_rows(cd["date"], cd["department"])
        return self.render_to_response(self.get_context_data(rows=rows, editable=editable))

    def post(self, request, *args, **kwargs):
        self.filter = self.get_filter()
        cd = self.filter.cleaned_data
        rows, editable = self.build_rows(cd["date"], cd["department"], data=request.POST)
        if not editable:
            raise PermissionDenied
        if not all(row["form"].is_valid() for row in rows):
            messages.error(request, "工位選項不正確，請重新選擇。")
            return self.render_to_response(self.get_context_data(rows=rows, editable=editable))
        changes = [
            {"record": row["record"], "old": row["record"].station, "new": row["form"].cleaned_data["station"]}
            for row in rows
            if row["form"].has_changed()
        ]
        if not changes:
            messages.info(request, "沒有變更。")
            return self.redirect_back(cd)
        if request.POST.get("action") != "confirm":
            return self.render_to_response(self.get_context_data(rows=rows, editable=editable, changes=changes))
        with transaction.atomic():
            for change in changes:
                record = change["record"]
                record.station = change["new"]
                record.updated_by = request.user
                record.save()
        messages.success(request, f"已確認修改 {len(changes)} 人的工位。")
        return self.redirect_back(cd)

    def redirect_back(self, cd):
        return redirect(f"{self.request.path}?date={cd['date']:%Y-%m-%d}&department={cd['department'].pk}")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter"] = self.filter
        context["date"] = self.filter.cleaned_data["date"]
        context["is_today"] = context["date"] == timezone.localdate()
        return context


class HeadcountView(AttendanceMixin, TemplateView):
    """某一天各部門、各工位的到班人數。"""

    page_key = "attendance-headcount"
    template_name = "attendance/headcount.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        self.filter = self.get_filter()
        date = self.filter.cleaned_data["date"]
        records = Attendance.objects.filter(date=date, employee__department__in=self.departments).select_related(
            "employee", "station__department"
        )
        active = Employee.objects.filter(is_active=True, department__in=self.departments).values_list("pk", "department_id")
        summary = []
        for department in self.departments:
            dept_records = [r for r in records if r.employee.department_id == department.pk]
            registered = {r.employee_id for r in dept_records}
            active_ids = [pk for pk, dept_id in active if dept_id == department.pk]
            status = Counter(r.status for r in dept_records)
            # 支援其他部門工位時會顯示「部門／工位」
            stations = Counter(
                (r.station.name if r.station.department_id == department.pk else str(r.station)) if r.station else "未填工位"
                for r in dept_records
                if r.status == Status.PRESENT
            )
            summary.append({
                "department": department,
                "active": len(active_ids),
                "present": status[Status.PRESENT],
                "leave": status[Status.LEAVE],
                "absent": status[Status.ABSENT],
                "unregistered": len([pk for pk in active_ids if pk not in registered]),
                "stations": sorted(stations.items()),
            })
        context.update(filter=self.filter, date=date, summary=summary,
                       total_present=sum(s["present"] for s in summary))
        return context
