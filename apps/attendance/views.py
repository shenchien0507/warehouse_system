import datetime
from collections import Counter

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.generic import TemplateView

from apps.accounts.levels import allows
from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.personnel.models import Employee

from .forms import DateForm, EventForm, LookupForm, StationAssignForm
from .models import PRESENT_STATUSES, Attendance, AttendanceEvent, EventKind, StationBatch, StationBatchEntry, Status
from .records import add_event, batch_diff, changes_since, now_minute, timeline, void_event
from .rules import (
    can_add, can_arrange, can_register, can_void, departments_in_scope, employees_in_scope, station_departments,
)

NO_DEPARTMENT = "none"  # 人員沒有設定部門時，統計與名單用的代碼（只有經理以上看得到）
QUICK = {"clock_in": EventKind.CLOCK_IN, "clock_out": EventKind.CLOCK_OUT, "leave_out": EventKind.LEAVE_OUT}
MISSING_CLOCK_OUT_DAYS = 7  # 提醒最近幾天沒有下班紀錄的人


def here_now(record, is_today):
    """「現在」的人：今天是目前在場的人；之前的日期沒有「現在」，算當天來過的人。"""
    return record.on_site if is_today else record.came


def quick_event(user, employee, kind, date, note=""):
    """按上班、下班、請假離開：記下現在的時間；回傳 (到班紀錄, 錯誤訊息)。"""
    if not employee.is_active and not Attendance.objects.filter(employee=employee, date=date).exists():
        return None, f"{employee} 已離職，不能登記到班。"
    return add_event(employee, date, user, kind, now_minute(), note=note)


def missing_clock_out(user):
    """最近幾天上了班卻沒有離開紀錄的人，提醒補登下班時間。"""
    today = timezone.localdate()
    return (
        Attendance.objects.filter(
            date__lt=today, date__gte=today - datetime.timedelta(days=MISSING_CLOCK_OUT_DAYS), on_site=True,
            employee__in=employees_in_scope(user),
        )
        .select_related("employee")
        .order_by("-date", "employee__employee_no")
    )


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
        return allows(user, "attendance-register-all") or (allows(user, "attendance-register-own") and bool(user.department_id))


def scope_entries(user):
    """統計與名單的範圍：可登記的部門；經理以上再加上「未設定部門」（有這類人員時）。"""
    entries = [{"key": str(d.pk), "label": str(d), "department": d} for d in departments_in_scope(user)]
    if allows(user, "attendance-register-all") and Employee.objects.filter(department__isnull=True).exists():
        entries.append({"key": NO_DEPARTMENT, "label": "未設定部門", "department": None})
    return entries


def summarize(user, date):
    """某一天各部門的人數。當天狀況互不重疊：到班（全天）、部分請假、請假、缺勤、未登記，加起來就是在職人數；
    「現在」另外算：目前在場，以及在場的人所在工位（之前的日期算當天來過的人）。"""
    entries = scope_entries(user)
    is_today = date == timezone.localdate()
    records = Attendance.objects.filter(date=date).exclude(status="").select_related("employee", "station")
    active = Employee.objects.filter(is_active=True).values_list("pk", "department_id")
    summary = []
    for entry in entries:
        dept_id = entry["department"].pk if entry["department"] else None
        dept_records = [r for r in records if r.employee.department_id == dept_id]
        registered = {r.employee_id for r in dept_records}
        active_ids = [pk for pk, d in active if d == dept_id]
        status = Counter(r.status for r in dept_records)
        stations = Counter(
            (str(r.station.pk), r.station.name) if r.station else ("none", "未填工位")
            for r in dept_records
            if here_now(r, is_today)
        )
        summary.append({
            **entry,
            "active": len(active_ids),
            "came": status[Status.PRESENT] + status[Status.PARTIAL],
            "present": status[Status.PRESENT],
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
    MAX_CANDIDATES = 20

    def load(self):
        """依網址的工號（或姓名）與日期找出人員與當天紀錄。"""
        lookup = LookupForm(self.request.GET)
        lookup.is_valid()
        self.date = lookup.cleaned_data.get("date") or timezone.localdate()
        self.employee_no = lookup.cleaned_data.get("employee_no", "")
        self.employee = self.record = None
        self.candidates = []
        self.error = ""
        if not self.employee_no:
            return
        self.employee = self.find(self.employee_no)
        if self.candidates:
            return
        if not self.employee:
            self.error = f"找不到工號或姓名「{self.employee_no}」的人員。"
        elif not can_register(self.request.user, self.employee):
            self.employee = None
            self.error = "這位人員不在你可以登記的範圍內。"
        else:
            self.record = Attendance.objects.filter(employee=self.employee, date=self.date).select_related("station").first()
            if not self.employee.is_active and not self.record:
                self.error = f"{self.employee} 已離職，不能登記到班。"
                self.employee = None
            else:
                self.employee_no = self.employee.employee_no

    def find(self, query):
        """先找完全相同的工號（下拉選單選的「工號 姓名」取第一段）；找不到再用姓名或部分工號在可登記範圍內找在職人員。
        只找到一個就直接帶出，找到多個就列出來讓人選。"""
        people = Employee.objects.select_related("department")
        for key in dict.fromkeys((query, query.split()[0])):
            found = people.filter(employee_no__iexact=key).first()
            if found:
                return found
        matches = list(
            employees_in_scope(self.request.user).filter(is_active=True)
            .filter(Q(name__icontains=query) | Q(employee_no__icontains=query))
            .select_related("department")[: self.MAX_CANDIDATES + 1]
        )
        if len(matches) == 1:
            return matches[0]
        self.candidates = matches
        return None

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
        if action in QUICK:
            if self.date != timezone.localdate():
                messages.error(request, "只有今天可以直接按上班、下班；其他日期請用「補登紀錄」填時間。")
            elif self.save_event(QUICK[action], now_minute(), note=request.POST.get("quick_note", "").strip()[:200]):
                return self.redirect_back(keep_employee=False)
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
        """按上班、下班、補登成功後回到空白的工號欄，方便登記下一個人；作廢或登記失敗留在這個人。"""
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
            can_clock=editable and self.date == today, candidates=self.candidates[: self.MAX_CANDIDATES],
            more_candidates=len(self.candidates) > self.MAX_CANDIDATES,
            options=employees_in_scope(user).filter(is_active=True).order_by("employee_no"),
            missing_clock_out=missing_clock_out(user), can_fix_past=allows(user, "attendance-past-dates"),
            summary=summarize(user, self.date),
        )
        context["total_came"] = sum(row["came"] for row in context["summary"])
        context["total_present"] = sum(row["present"] for row in context["summary"])
        context["total_partial"] = sum(row["partial"] for row in context["summary"])
        context["total_on_site"] = sum(row["on_site"] for row in context["summary"])
        return context


class PersonListView(RegisterAccessMixin, TemplateView):
    """從人數統計點進來的人員名單。今天可以直接按每一列的上班、下班，或勾選多人一次上班、下班；
    其他登記（請假、補登、作廢）按「登記」去登記頁。"""

    template_name = "attendance/person_list.html"
    KINDS = {
        "active": "在職", "came": "今天來過", "present": "到班", "partial": "部分請假", "leave": "請假", "absent": "缺勤",
        "on_site": "目前在場", "unregistered": "未登記", "station": "依工位",
    }

    def post(self, request, *args, **kwargs):
        context = self.get_context_data()
        if not context["can_clock"]:
            raise PermissionDenied
        action, _, one = request.POST.get("do", "").partition(":")
        if action not in ("clock_in", "clock_out"):
            raise Http404
        listed = {str(row["employee"].pk): row["employee"] for row in context["rows"]}
        employees = [listed[pk] for pk in dict.fromkeys([one] if one else request.POST.getlist("employee")) if pk in listed]
        if not employees:
            messages.warning(request, "請先勾選人員。")
            return redirect(request.get_full_path())
        done, errors = [], []
        for employee in employees:
            _, error = quick_event(request.user, employee, QUICK[action], context["date"])
            if error:
                errors.append(f"{employee.name}：{error}")
            else:
                done.append(employee.name)
        label = EventKind(QUICK[action]).label
        if done:
            messages.success(request, f"{len(done)} 人{label} {now_minute():%H:%M}：{'、'.join(done)}。")
        for error in errors:
            messages.error(request, error)
        return redirect(request.get_full_path())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        date = self.get_date()
        key = self.request.GET.get("department", "")
        entry = next((e for e in scope_entries(self.request.user) if e["key"] == key), None)
        kind = self.request.GET.get("kind", "")
        if entry is None or kind not in self.KINDS:
            raise Http404
        department = entry["department"]
        employees = Employee.objects.filter(department=department).order_by("employee_no")
        records = Attendance.objects.filter(date=date, employee__department=department).select_related(
            "station"
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
            is_today = date == timezone.localdate()
            present = records.filter(on_site=True) if is_today else records.filter(status__in=PRESENT_STATUSES)
            title = f"{entry['label']}　{'目前在場' if is_today else '當天來過'}（依工位）"
            if station == "none":
                present, name = present.filter(station__isnull=True), "未填工位"
            else:
                present = present.filter(station_id=station if station.isdigit() else 0)
                name = str(present[0].station) if present else "工位"
            title += f"　{name}"
            rows = [{"employee": r.employee, "record": r} for r in present]
        else:
            filters = {"came": {"status__in": PRESENT_STATUSES}, "on_site": {"on_site": True}}.get(kind, {"status": kind})
            rows = [{"employee": r.employee, "record": r} for r in records.filter(**filters)]
        is_today = date == timezone.localdate()
        can_clock = is_today and can_add(self.request.user, date)
        context.update(
            date=date, title=title, rows=rows, department_key=key, is_today=is_today, can_clock=can_clock,
            can_clock_in=can_clock and any(not (r["record"] and r["record"].on_site) for r in rows),
            can_clock_out=can_clock and any(r["record"] and r["record"].on_site for r in rows),
        )
        return context


class StationScopeMixin(PageMixin):
    page_key = "attendance-stations"

    def check_scope(self, user):
        return allows(user, "attendance-stations-all") or bool(user.department_id)

    def in_scope(self, queryset, field="employee__department__in"):
        """可安排全部部門的人看全部，其他人只看自己部門。"""
        if not allows(self.request.user, "attendance-stations-all"):
            queryset = queryset.filter(**{field: station_departments(self.request.user)})
        return queryset

    def can_see(self, employee):
        user = self.request.user
        if not hasattr(self, "_scope_ids"):
            self._scope_ids = set(station_departments(user).values_list("pk", flat=True))
        return allows(user, "attendance-stations-all") or employee.department_id in self._scope_ids


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
            "entries__employee__department", "entries__station"
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


class StationCreateView(StationScopeMixin, TemplateView):
    """建立安排：今天列出目前在場的人，之前的日期列出當天上過班的人；手動安排當日工位。
    改完先列出變更，確認後批次儲存並建立一筆批次紀錄。
    工位沒改、但名單和目前生效的批次不同（有人離開或新到）也算變更，可以建立新批次。"""

    template_name = "attendance/station_form.html"

    def build_rows(self, date, data=None):
        here = {"on_site": True} if date == timezone.localdate() else {"clock_in__isnull": False}
        records = self.in_scope(
            Attendance.objects.filter(date=date, **here)
            .select_related("employee__department", "station")
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
        left, arrived = self.roster_changes(rows)
        if not changes and not left and not arrived:
            messages.info(request, "沒有變更，沒有建立新的安排。")
            return self.redirect_back()
        if request.POST.get("action") != "confirm":
            return self.render_to_response(
                self.get_context_data(rows=rows, editable=editable, changes=changes, left=left, arrived=arrived, previewing=True)
            )
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
        roster = "、".join(text for text in (f"離開 {len(left)} 人" if left else "", f"新到 {len(arrived)} 人" if arrived else "") if text)
        messages.success(request, f"已建立安排，修改 {len(changes)} 人的工位{f'（名單{roster}）' if roster else ''}。")
        return self.redirect_back()

    def roster_changes(self, rows):
        """和目前生效的批次比，誰已經不在名單上、誰是新到的。當天還沒有批次時，所有人都算新到。"""
        latest = StationBatch.objects.filter(date=self.date).prefetch_related("entries__employee").first()
        before = {e.employee_id: e.employee for e in latest.entries.all() if self.can_see(e.employee)} if latest else {}
        now = {row["record"].employee_id for row in rows}
        left = [employee for pk, employee in before.items() if pk not in now]
        arrived = [row["record"].employee for row in rows if row["record"].employee_id not in before]
        return left, arrived

    def redirect_back(self):
        return redirect(f"{reverse('attendance:stations')}?{urlencode({'date': f'{self.date:%Y-%m-%d}'})}")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(date=self.date, is_today=self.date == timezone.localdate())
        return context
