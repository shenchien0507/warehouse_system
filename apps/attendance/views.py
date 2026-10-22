from collections import Counter

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.generic import TemplateView

from apps.accounts.models import Level
from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.personnel.models import Employee

from .forms import AttendanceRowForm, DateForm, LookupForm, StationAssignForm
from .models import Attendance, StationBatch, StationBatchEntry, Status
from .rules import can_arrange, can_edit, can_register, departments_in_scope, station_departments

NO_DEPARTMENT = "none"  # 人員沒有設定部門時，統計與名單用的代碼（只有經理以上看得到）


class PageMixin:
    """頁面權限檢查；範圍不足（例如沒有部門）時提示並回首頁。"""

    page_key = None

    def check_scope(self, user):
        return True

    def dispatch(self, request, *args, **kwargs):
        if not can_use(request.user, MENU_BY_KEY[self.page_key]):
            raise PermissionDenied
        if not self.check_scope(request.user):
            messages.warning(request, "你的帳號沒有設定部門，或職級不足，不能使用這個功能。")
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def get_date(self):
        form = DateForm(self.request.GET)
        form.is_valid()
        return form.cleaned_data.get("date") or timezone.localdate()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_item"] = MENU_BY_KEY[self.page_key]
        return context


class RegisterAccessMixin(PageMixin):
    page_key = "attendance-register"

    def check_scope(self, user):
        return user.level >= Level.MANAGER or (user.level >= Level.LEADER and bool(user.department_id))


def scope_entries(user):
    """統計與名單的範圍：可登記的部門；經理以上再加上「未設定部門」（有這類人員時）。"""
    entries = [{"key": str(d.pk), "label": str(d), "department": d} for d in departments_in_scope(user)]
    if user.level >= Level.MANAGER and Employee.objects.filter(department__isnull=True).exists():
        entries.append({"key": NO_DEPARTMENT, "label": "未設定部門", "department": None})
    return entries


def summarize(user, date):
    """某一天各部門、各工位的到班人數。"""
    entries = scope_entries(user)
    records = Attendance.objects.filter(date=date).select_related("employee", "station__department")
    active = Employee.objects.filter(is_active=True).values_list("pk", "department_id")
    summary = []
    for entry in entries:
        dept_id = entry["department"].pk if entry["department"] else None
        dept_records = [r for r in records if r.employee.department_id == dept_id]
        registered = {r.employee_id for r in dept_records}
        active_ids = [pk for pk, d in active if d == dept_id]
        status = Counter(r.status for r in dept_records)
        # 支援其他部門工位時會顯示「部門／工位」
        stations = Counter(
            (
                (str(r.station.pk), r.station.name if r.station.department_id == dept_id else str(r.station))
                if r.station
                else ("none", "未填工位")
            )
            for r in dept_records
            if r.status == Status.PRESENT
        )
        summary.append({
            **entry,
            "active": len(active_ids),
            "present": status[Status.PRESENT],
            "leave": status[Status.LEAVE],
            "absent": status[Status.ABSENT],
            "unregistered": len([pk for pk in active_ids if pk not in registered]),
            "stations": [{"key": key, "label": label, "count": count} for (key, label), count in sorted(stations.items(), key=lambda i: i[0][1])],
        })
    return summary


class RegisterView(RegisterAccessMixin, TemplateView):
    """輸入工號查出人員，按「上班」「下班」記錄時間；按上班會自動把狀態設為到班。也可手動改狀態、時間與備註。"""

    page_key = "attendance-register"
    template_name = "attendance/register.html"

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
            return self.redirect_back(keep_employee=False)
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

    def redirect_back(self, keep_employee=True):
        """按上班、下班後留在這個人；儲存修改後回到搜尋畫面。"""
        params = {"date": f"{self.date:%Y-%m-%d}"}
        if keep_employee:
            params["employee_no"] = self.employee_no
        return redirect(f"{self.request.path}?{urlencode(params)}")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        context.update(
            menu_item=MENU_BY_KEY[self.page_key], date=self.date, employee_no=self.employee_no, employee=self.employee,
            record=self.record, error=self.error, is_today=self.date == today,
            can_clock=self.employee is not None and self.date == today and can_edit(self.request.user, self.date, self.record),
            summary=summarize(self.request.user, self.date),
        )
        context["total_present"] = sum(row["present"] for row in context["summary"])
        return context


class PersonListView(RegisterAccessMixin, TemplateView):
    """從人數統計點進來的人員名單；每個人可以點「登記」去設定。"""

    template_name = "attendance/person_list.html"
    KINDS = {"active": "在職", "present": "到班", "leave": "請假", "absent": "缺勤", "unregistered": "未登記", "station": "到班（依工位）"}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        date = self.get_date()
        key = self.request.GET.get("department", "")
        entry = next((e for e in scope_entries(self.request.user) if e["key"] == key), None)
        kind = self.request.GET.get("kind", "")
        if entry is None or kind not in self.KINDS:
            raise Http404
        department = entry["department"]
        employees = Employee.objects.filter(department=department).select_related("job_title").order_by("employee_no")
        records = Attendance.objects.filter(date=date, employee__department=department).select_related(
            "employee__job_title", "station__department"
        ).order_by("employee__employee_no")
        title = f"{entry['label']}　{self.KINDS[kind]}"
        if kind == "active":
            by_record = {r.employee_id: r for r in records}
            rows = [{"employee": e, "record": by_record.get(e.pk)} for e in employees.filter(is_active=True)]
        elif kind == "unregistered":
            registered = set(records.values_list("employee_id", flat=True))
            rows = [{"employee": e, "record": None} for e in employees.filter(is_active=True) if e.pk not in registered]
        elif kind == "station":
            station = self.request.GET.get("station", "")
            present = records.filter(status=Status.PRESENT)
            if station == "none":
                present, name = present.filter(station__isnull=True), "未填工位"
            else:
                present = present.filter(station_id=station if station.isdigit() else 0)
                name = str(present[0].station) if present else "工位"
            title += f"　{name}"
            rows = [{"employee": r.employee, "record": r} for r in present]
        else:
            rows = [{"employee": r.employee, "record": r} for r in records.filter(status=kind)]
        context.update(date=date, title=title, rows=rows, department_key=key)
        return context


class StationScopeMixin(PageMixin):
    page_key = "attendance-stations"

    def check_scope(self, user):
        return user.level >= Level.MANAGER or bool(user.department_id)

    def in_scope(self, queryset, field="employee__department__in"):
        """經理以上看全部，其他人只看自己部門。"""
        if self.request.user.level < Level.MANAGER:
            queryset = queryset.filter(**{field: station_departments(self.request.user)})
        return queryset


class StationListView(StationScopeMixin, TemplateView):
    """工位安排首頁：按「建立安排」才進入編輯；下方列出當天已建立的批次，顯示各部門人數，可展開看詳細工位。"""

    template_name = "attendance/stations.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        date = self.get_date()
        batches = StationBatch.objects.filter(date=date).select_related("created_by").prefetch_related(
            "entries__employee__department", "entries__employee__job_title", "entries__station__department"
        )
        rows = []
        for batch in batches:
            entries = [e for e in batch.entries.all() if self.can_see(e.employee)]
            if not entries:
                continue
            entries.sort(key=lambda e: (e.employee.department.name if e.employee.department else "", e.employee.employee_no))
            counts = Counter(e.employee.department.name if e.employee.department else "未設定部門" for e in entries)
            rows.append({"batch": batch, "entries": entries, "total": len(entries), "departments": sorted(counts.items())})
        if rows:
            rows[0]["current"] = True
        context.update(date=date, batches=rows, can_create=can_arrange(self.request.user, date), is_today=date == timezone.localdate())
        return context

    def can_see(self, employee):
        user = self.request.user
        return user.level >= Level.MANAGER or employee.department_id in set(station_departments(user).values_list("pk", flat=True))


class StationCreateView(StationScopeMixin, TemplateView):
    """建立安排：列出當天到班人員，手動安排當日工位。改完先列出變更，確認後批次儲存並建立一筆批次紀錄。"""

    template_name = "attendance/station_form.html"

    def build_rows(self, date, data=None):
        records = self.in_scope(
            # 上午有到、中途請假的人（有上班時間或已排工位）也要列出，才能繼續調整工位
            Attendance.objects.filter(date=date)
            .filter(Q(status=Status.PRESENT) | Q(status=Status.LEAVE, clock_in__isnull=False) | Q(status=Status.LEAVE, station__isnull=False))
            .select_related("employee__job_title", "employee__department", "station__department")
            .order_by("employee__department__name", "employee__employee_no")
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
        self.date = self.get_date()
        rows, editable = self.build_rows(self.date)
        if not editable:
            raise PermissionDenied
        return self.render_to_response(self.get_context_data(rows=rows, editable=editable))

    def post(self, request, *args, **kwargs):
        self.date = self.get_date()
        rows, editable = self.build_rows(self.date, data=request.POST)
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
            messages.info(request, "沒有變更，沒有建立新的安排。")
            return self.redirect_back()
        if request.POST.get("action") != "confirm":
            return self.render_to_response(self.get_context_data(rows=rows, editable=editable, changes=changes))
        with transaction.atomic():
            for change in changes:
                record = change["record"]
                record.station = change["new"]
                record.updated_by = request.user
                record.save()
            batch = StationBatch.objects.create(date=self.date, created_by=request.user)
            StationBatchEntry.objects.bulk_create(
                StationBatchEntry(batch=batch, employee=row["record"].employee, station=row["form"].cleaned_data["station"])
                for row in rows
            )
        messages.success(request, f"已建立安排，修改 {len(changes)} 人的工位。")
        return self.redirect_back()

    def redirect_back(self):
        return redirect(f"{reverse('attendance:stations')}?{urlencode({'date': f'{self.date:%Y-%m-%d}'})}")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["date"] = self.date
        return context
