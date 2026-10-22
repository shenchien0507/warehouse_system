from collections import Counter

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.generic import TemplateView

from apps.accounts.models import Level
from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.personnel.models import Employee

from .forms import DateForm, EventForm, LookupForm, StationAssignForm
from .models import PRESENT_STATUSES, Attendance, AttendanceEvent, EventKind, StationBatch, StationBatchEntry, Status
from .records import add_event, batch_diff, changes_since, now_minute, timeline, void_event
from .rules import can_add, can_arrange, can_register, can_void, departments_in_scope, station_departments

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
    """某一天各部門的到班人數：到班（含部分請假）、部分請假、請假、缺勤、未登記、目前在場，以及到班人員所在工位。"""
    entries = scope_entries(user)
    records = Attendance.objects.filter(date=date).exclude(status="").select_related("employee", "station__department")
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
            if r.status in PRESENT_STATUSES
        )
        summary.append({
            **entry,
            "active": len(active_ids),
            "present": status[Status.PRESENT] + status[Status.PARTIAL],
            "partial": status[Status.PARTIAL],
            "leave": status[Status.LEAVE],
            "absent": status[Status.ABSENT],
            "on_site": sum(1 for r in dept_records if r.on_site),
            "unregistered": len([pk for pk in active_ids if pk not in registered]),
            "stations": [{"key": key, "label": label, "count": count} for (key, label), count in sorted(stations.items(), key=lambda i: i[0][1])],
        })
    return summary


class RegisterView(RegisterAccessMixin, TemplateView):
    """輸入工號查出人員，按「上班」「下班」「請假離開」記錄現在的時間；也可補登指定時間的紀錄或請假。
    紀錄只累加不覆蓋，登記錯了用作廢；當天狀態由紀錄算出來。"""

    page_key = "attendance-register"
    template_name = "attendance/register.html"
    QUICK = {"clock_in": EventKind.CLOCK_IN, "clock_out": EventKind.CLOCK_OUT, "leave_out": EventKind.LEAVE_OUT}

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
            self.record = Attendance.objects.filter(employee=self.employee, date=self.date).select_related("station").first()
            if not self.employee.is_active and not self.record:
                self.error = f"{self.employee} 已離職，不能登記到班。"
                self.employee = None

    def get(self, request, *args, **kwargs):
        self.load()
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        self.load()
        if not self.employee:
            messages.error(request, self.error or "請先輸入工號。")
            return self.redirect_back()
        if not can_add(request.user, self.date):
            raise PermissionDenied
        action = request.POST.get("action")
        if action in self.QUICK:
            if self.date != timezone.localdate():
                messages.error(request, "只有今天可以直接按上班、下班；其他日期請用「補登紀錄」填時間。")
            else:
                self.save_event(self.QUICK[action], now_minute(), note=request.POST.get("quick_note", "").strip()[:200])
        elif action == "add":
            form = EventForm(request.POST, prefix="e")
            if not form.is_valid():
                messages.error(request, "有欄位不正確，請檢查標紅的地方。")
                return self.render_to_response(self.get_context_data(event_form=form))
            values = form.cleaned_data
            if not self.save_event(values["kind"], values["time"], values["end_time"], values["note"]):
                return self.render_to_response(self.get_context_data(event_form=form))
            return self.redirect_back(keep_employee=False)
        elif action == "void":
            event = get_object_or_404(AttendanceEvent, pk=request.POST.get("event"), attendance=self.record)
            if not can_void(request.user, event):
                raise PermissionDenied
            void_event(event, request.user)
            messages.success(request, f"已作廢「{event.describe()}」。")
        return self.redirect_back()

    def save_event(self, kind, time, end_time=None, note=""):
        self.record, error = add_event(self.employee, self.date, self.request.user, kind, time, end_time, note)
        if error:
            messages.error(self.request, f"{self.employee.name}：{error}")
            return False
        event = self.record.events.latest("created_at", "pk")
        messages.success(self.request, f"{self.employee.name} {event.describe()}，目前狀態：{self.record.get_status_display()}。")
        return True

    def redirect_back(self, keep_employee=True):
        """按上班、下班、作廢後留在這個人；補登後回到搜尋畫面。"""
        params = {"date": f"{self.date:%Y-%m-%d}"}
        if keep_employee:
            params["employee_no"] = self.employee_no
        return redirect(f"{self.request.path}?{urlencode(params)}")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today, user = timezone.localdate(), self.request.user
        events = []
        if self.record:
            for event in self.record.events.select_related("created_by", "voided_by"):
                event.can_void = can_void(user, event)
                events.append(event)
        editable = self.employee is not None and can_add(user, self.date)
        if editable and "event_form" not in kwargs:
            context["event_form"] = EventForm(prefix="e", initial={"time": now_minute() if self.date == today else None})
        context.update(
            menu_item=MENU_BY_KEY[self.page_key], date=self.date, employee_no=self.employee_no, employee=self.employee,
            record=self.record, events=events, error=self.error, is_today=self.date == today, editable=editable,
            can_clock=editable and self.date == today,
            summary=summarize(user, self.date),
        )
        context["total_present"] = sum(row["present"] for row in context["summary"])
        context["total_on_site"] = sum(row["on_site"] for row in context["summary"])
        return context


class PersonListView(RegisterAccessMixin, TemplateView):
    """從人數統計點進來的人員名單；每個人可以點「登記」去設定。"""

    template_name = "attendance/person_list.html"
    KINDS = {
        "active": "在職", "present": "到班", "partial": "部分請假", "leave": "請假", "absent": "缺勤",
        "on_site": "目前在場", "unregistered": "未登記", "station": "到班（依工位）",
    }

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
            registered = set(records.exclude(status="").values_list("employee_id", flat=True))
            rows = [{"employee": e, "record": None} for e in employees.filter(is_active=True) if e.pk not in registered]
        elif kind == "station":
            station = self.request.GET.get("station", "")
            present = records.filter(status__in=PRESENT_STATUSES)
            if station == "none":
                present, name = present.filter(station__isnull=True), "未填工位"
            else:
                present = present.filter(station_id=station if station.isdigit() else 0)
                name = str(present[0].station) if present else "工位"
            title += f"　{name}"
            rows = [{"employee": r.employee, "record": r} for r in present]
        else:
            filters = {"present": {"status__in": PRESENT_STATUSES}, "on_site": {"on_site": True}}.get(kind, {"status": kind})
            rows = [{"employee": r.employee, "record": r} for r in records.filter(**filters)]
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
    """工位安排首頁：按「建立安排」才進入編輯。上方提示目前生效的批次之後誰離開、誰新到；
    下方可切換「批次」（各部門人數、和上一批的差別，可展開看詳細工位）與「時間軸」。"""

    template_name = "attendance/stations.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        date = self.get_date()
        is_today = date == timezone.localdate()
        view = "timeline" if self.request.GET.get("view") == "timeline" else "batches"
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
        for i, row in enumerate(rows):
            row["diff"] = batch_diff(row["entries"], rows[i + 1]["entries"] if i + 1 < len(rows) else None)
        changes = []
        if rows:
            rows[0]["current"] = True
            if is_today:
                on_site = list(self.in_scope(Attendance.objects.filter(date=date, on_site=True).select_related("employee__department")))
                changes = changes_since(date, rows[0]["entries"], on_site)
                context["on_site_count"] = len(on_site)
        context.update(
            date=date, batches=rows, changes=changes, view=view, is_today=is_today,
            can_create=can_arrange(self.request.user, date),
            timeline=timeline(date, self.can_see) if view == "timeline" else None,
        )
        return context

    def can_see(self, employee):
        user = self.request.user
        if not hasattr(self, "_scope_ids"):
            self._scope_ids = set(station_departments(user).values_list("pk", flat=True))
        return user.level >= Level.MANAGER or employee.department_id in self._scope_ids


class StationCreateView(StationScopeMixin, TemplateView):
    """建立安排：今天列出目前在場的人，之前的日期列出當天上過班的人；手動安排當日工位。
    改完先列出變更，確認後批次儲存並建立一筆批次紀錄。"""

    template_name = "attendance/station_form.html"

    def build_rows(self, date, data=None):
        here = {"on_site": True} if date == timezone.localdate() else {"clock_in__isnull": False}
        records = self.in_scope(
            Attendance.objects.filter(date=date, **here)
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
        context.update(date=self.date, is_today=self.date == timezone.localdate())
        return context
