"""到班登記、到班名單；工位安排在 station_views.py。"""

import datetime

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.http import urlencode
from django.views.generic import TemplateView

from apps.accounts.levels import allows
from apps.backoffice.menu import can_use
from apps.backoffice.views import PageMixin
from apps.personnel.models import Employee

from .forms import DateForm, EventForm, LookupForm
from .models import Attendance, AttendanceEvent, ClockSetting, EventKind
from .records import add_event, now_minute, void_event
from .rules import can_add, can_register, can_register_any, can_void, employees_in_scope

QUICK = {"clock_in": EventKind.CLOCK_IN, "clock_out": EventKind.CLOCK_OUT}
MISSING_CLOCK_OUT_DAYS = 7  # 提醒最近幾天沒有下班紀錄的人


def clock_windows():
    """上班、下班按鈕現在能不能按，以及可按的時段（後台「上下班時間」設定）。"""
    setting, now = ClockSetting.load(), now_minute()
    return {action: {"open": setting.allows(kind, now), "window": setting.describe(kind)} for action, kind in QUICK.items()}


def window_error(action):
    """不在按鈕可按的時段時回傳提示，否則回傳空字串。"""
    window = clock_windows()[action]
    if window["open"]:
        return ""
    return f"{EventKind(QUICK[action]).label}按鈕只在 {window['window']} 可以按，其他時間請用「補登紀錄」。"


def quick_event(user, employee, kind, date):
    """按上班、下班：記下現在的時間；回傳 (到班紀錄, 錯誤訊息)。"""
    if not employee.is_active and not Attendance.objects.filter(employee=employee, date=date).exists():
        return None, f"{employee} 已離職，不能登記到班。"
    return add_event(employee, date, user, kind, now_minute())


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


class AttendancePageMixin(PageMixin):
    """到班的頁面：頁面權限之外，check_scope 不通過（職級不足）時提示並回首頁。"""

    def check_scope(self, user):
        return True

    def dispatch(self, request, *args, **kwargs):
        if not can_use(request.user, self.menu_item):
            raise PermissionDenied
        if not self.check_scope(request.user):
            messages.warning(request, "你的職級不足，不能使用這個功能。")
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def get_date(self):
        form = DateForm(self.request.GET)
        form.is_valid()
        return form.cleaned_data.get("date") or timezone.localdate()


class RegisterAccessMixin(AttendancePageMixin):
    page_key = "attendance-register"

    def check_scope(self, user):
        return can_register_any(user)


def day_rows(user, date):
    """可登記範圍內的在職人員和他們當天的到班紀錄（沒有紀錄是 None）。"""
    employees = employees_in_scope(user).filter(is_active=True).select_related("level").order_by("employee_no")
    records = {r.employee_id: r for r in Attendance.objects.filter(date=date, employee__in=employees).select_related("station")}
    return [{"employee": e, "record": records.get(e.pk)} for e in employees]


def arrived(row):
    """實到：當天有打上班卡（部分請假但有來也算）。"""
    return bool(row["record"] and row["record"].came)


def on_site(row):
    return bool(row["record"] and row["record"].on_site)


# 人數統計與名單：應到＝在職人員；實到＝有打上班卡的人；未到＝其餘（請假、缺勤、未登記）
COUNTS = {
    "expected": ("應到", lambda row: True),
    "arrived": ("實到", arrived),
    "missing": ("未到", lambda row: not arrived(row)),
    "on_site": ("目前在場", on_site),
}


def summarize(user, date):
    rows = day_rows(user, date)
    return {key: sum(1 for row in rows if test(row)) for key, (_, test) in COUNTS.items()}


class RegisterView(RegisterAccessMixin, TemplateView):
    """輸入工號查出人員，按「上班」「下班」記錄現在的時間（只在後台設定的時段內可按）；其他時間、請假、缺勤用補登。
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
        people = Employee.objects.all()
        for key in dict.fromkeys((query, query.split()[0])):
            found = people.filter(employee_no__iexact=key).first()
            if found:
                return found
        matches = list(
            employees_in_scope(self.request.user).filter(is_active=True)
            .filter(Q(name__icontains=query) | Q(employee_no__icontains=query))
            [: self.MAX_CANDIDATES + 1]
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
            elif window_error(action):
                messages.error(request, window_error(action))
            elif self.save_event(QUICK[action], now_minute()):
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
            date=self.date, employee_no=self.employee_no, employee=self.employee,
            record=self.record, events=events, error=self.error, is_today=self.date == today, editable=editable,
            can_clock=editable and self.date == today, clock=clock_windows(), candidates=self.candidates[: self.MAX_CANDIDATES],
            more_candidates=len(self.candidates) > self.MAX_CANDIDATES,
            options=employees_in_scope(user).filter(is_active=True).order_by("employee_no"),
            missing_clock_out=missing_clock_out(user), can_fix_past=allows(user, "attendance-past-dates"),
            summary=summarize(user, self.date),
        )
        return context


class PersonListView(RegisterAccessMixin, TemplateView):
    """從人數（應到、實到、未到、目前在場）點進來的人員名單，今天可以直接按每一列的上班、下班，或勾選多人一次上班、下班；
    其他登記（請假、補登、作廢）按「登記」去登記頁。"""

    template_name = "attendance/person_list.html"

    def post(self, request, *args, **kwargs):
        context = self.get_context_data()
        if not context["can_clock"]:
            raise PermissionDenied
        action, _, one = request.POST.get("do", "").partition(":")
        if action not in QUICK:
            raise Http404
        if window_error(action):
            messages.error(request, window_error(action))
            return redirect(request.get_full_path())
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
        kind = self.request.GET.get("kind", "")
        if kind not in COUNTS:
            raise Http404
        title, test = COUNTS[kind]
        rows = [row for row in day_rows(self.request.user, date) if test(row)]
        is_today = date == timezone.localdate()
        can_clock = is_today and can_add(self.request.user, date)
        clock = clock_windows()
        context.update(
            date=date, title=title, rows=rows, is_today=is_today, can_clock=can_clock, clock=clock,
            can_clock_in=can_clock and clock["clock_in"]["open"] and any(not (r["record"] and r["record"].on_site) for r in rows),
            can_clock_out=can_clock and clock["clock_out"]["open"] and any(r["record"] and r["record"].on_site for r in rows),
        )
        return context
