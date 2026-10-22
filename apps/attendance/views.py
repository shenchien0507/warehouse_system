from collections import Counter

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import urlencode
from django.views.generic import TemplateView

from apps.accounts.models import Level
from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.personnel.models import Employee

from .forms import AttendanceRowForm, FilterForm, LookupForm, StationAssignForm
from .models import Attendance, Status
from .rules import can_arrange, can_edit, can_register, departments_in_scope, station_departments


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


class RegisterView(TemplateView):
    """輸入工號查出人員，按「上班」「下班」記錄時間；按上班會自動把狀態設為到班。也可手動改狀態、時間與備註。"""

    page_key = "attendance-register"
    template_name = "attendance/register.html"

    def dispatch(self, request, *args, **kwargs):
        if not can_use(request.user, MENU_BY_KEY[self.page_key]):
            raise PermissionDenied
        if request.user.level < Level.LEADER or (request.user.level < Level.MANAGER and not request.user.department_id):
            messages.warning(request, "你的帳號沒有設定部門，或職級不足，不能使用這個功能。")
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def load(self):
        """依網址的工號與日期找出人員與當天紀錄。"""
        lookup = LookupForm(self.request.GET)
        lookup.is_valid()
        self.date = lookup.cleaned_data.get("date") or timezone.localdate()
        self.employee_no = lookup.cleaned_data.get("employee_no", "")
        self.employee = self.record = None
        self.error = ""
        if not self.employee_no:
            return
        self.employee = Employee.objects.select_related("department", "job_title").filter(employee_no__iexact=self.employee_no).first()
        if not self.employee:
            self.error = f"找不到工號「{self.employee_no}」的人員。"
        elif not can_register(self.request.user, self.employee):
            self.employee = None
            self.error = "這位人員不在你可以登記的範圍內。"
        else:
            self.record = Attendance.objects.filter(employee=self.employee, date=self.date).select_related("created_by").first()
            if not self.employee.is_active and not self.record:
                self.error = f"{self.employee} 已離職，不能登記到班。"
                self.employee = None

    def make_form(self, data=None):
        initial = {}
        if self.record:
            initial = {f: getattr(self.record, f) for f in ("status", "clock_in", "clock_out", "station", "note")}
        return AttendanceRowForm(data, prefix="r", initial=initial, editable=can_edit(self.request.user, self.date, self.record))

    def get(self, request, *args, **kwargs):
        self.load()
        return self.render_to_response(self.get_context_data(form=self.make_form() if self.employee else None))

    def post(self, request, *args, **kwargs):
        self.load()
        if not self.employee:
            messages.error(request, self.error or "請先輸入工號。")
            return self.redirect_back()
        if not can_edit(request.user, self.date, self.record):
            raise PermissionDenied
        action = request.POST.get("action")
        if action in ("clock_in", "clock_out"):
            self.clock(action)
        else:
            form = self.make_form(request.POST)
            if not form.is_valid():
                messages.error(request, "有欄位格式不正確，請檢查標紅的地方。")
                return self.render_to_response(self.get_context_data(form=form))
            self.save_form(form)
        return self.redirect_back()

    def clock(self, action):
        request, record = self.request, self.record
        if self.date != timezone.localdate():
            messages.error(request, "只有今天可以按上班、下班；其他日期請直接修改時間。")
            return
        now = timezone.localtime().time().replace(second=0, microsecond=0)
        if action == "clock_in":
            if record and record.clock_in:
                messages.info(request, f"{self.employee.name} 已在 {record.clock_in:%H:%M} 上班。")
                return
            if record is None:
                record = Attendance(employee=self.employee, date=self.date, created_by=request.user)
            record.status, record.clock_in = Status.PRESENT, now
            message = f"{self.employee.name} 上班 {now:%H:%M}，狀態：到班。"
        else:
            if record is None or record.status != Status.PRESENT or not record.clock_in:
                messages.error(request, f"{self.employee.name} 還沒有上班紀錄，請先按「上班」。")
                return
            if record.clock_out:
                messages.info(request, f"{self.employee.name} 已在 {record.clock_out:%H:%M} 下班。")
                return
            record.clock_out = now
            message = f"{self.employee.name} 下班 {now:%H:%M}。"
        record.updated_by = request.user
        record.save()
        messages.success(request, message)

    def save_form(self, form):
        request, record = self.request, self.record
        if not form.has_changed():
            messages.info(request, "沒有變更。")
            return
        values = form.cleaned_data
        if not values["status"]:
            if record:
                record.delete()
                messages.success(request, "已清除這天的登記。")
            return
        if record is None:
            record = Attendance(employee=self.employee, date=self.date, created_by=request.user)
        for field in ("status", "clock_in", "clock_out", "station", "note"):
            setattr(record, field, values[field])
        record.updated_by = request.user
        record.save()
        messages.success(request, f"已儲存 {self.employee.name} 的紀錄。")

    def redirect_back(self):
        return redirect(f"{self.request.path}?{urlencode({'employee_no': self.employee_no, 'date': f'{self.date:%Y-%m-%d}'})}")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        context.update(
            menu_item=MENU_BY_KEY[self.page_key], date=self.date, employee_no=self.employee_no, employee=self.employee,
            record=self.record, error=self.error, is_today=self.date == today,
            can_clock=self.employee is not None and self.date == today and can_edit(self.request.user, self.date, self.record),
        )
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
