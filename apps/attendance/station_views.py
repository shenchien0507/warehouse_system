"""工位安排：安排到班人員的工位，每次確認儲存記成一批；同時只能一個人編輯（編輯鎖）。"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.levels import allows
from apps.accounts.models import Station

from . import locks
from .forms import DateForm, StationAssignForm
from .models import Attendance, StationBatch, StationBatchEntry, StationEditLock
from .records import batch_diff, changes_since, same_entries, station_counts, timeline
from .rules import can_arrange
from .views import PageMixin


class StationPageMixin(PageMixin):
    page_key = "attendance-stations"


class StationListView(StationPageMixin, TemplateView):
    """工位安排首頁：按「建立安排」才進入編輯。上方是各工位人數，以及目前生效的批次之後誰離開、誰新到；
    下方可切換「批次」（各工位人數、和上一批的差別，可展開看詳細工位）與「時間軸」。
    人員和工位跟上一批完全一樣的批次不列出。"""

    template_name = "attendance/stations.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        date = self.get_date()
        is_today = date == timezone.localdate()
        view = "timeline" if self.request.GET.get("view") == "timeline" else "batches"
        batches = StationBatch.objects.filter(date=date).select_related("created_by").prefetch_related(
            "entries__employee__level", "entries__station"
        )
        rows = []
        for batch in batches:
            entries = sorted(batch.entries.all(), key=lambda e: e.employee.employee_no)
            if not entries:
                continue
            rows.append({
                "batch": batch, "entries": entries, "total": len(entries),
                "stations": station_counts(e.station for e in entries),
            })
        rows = [row for i, row in enumerate(rows) if i + 1 == len(rows) or not same_entries(row["entries"], rows[i + 1]["entries"])]
        for i, row in enumerate(rows):
            row["diff"] = batch_diff(row["entries"], rows[i + 1]["entries"] if i + 1 < len(rows) else None)
        changes, stations = [], None
        if is_today:
            on_site = list(Attendance.objects.filter(date=date, on_site=True).select_related("employee", "station"))
            stations = station_counts(r.station for r in on_site)
            context["on_site_count"] = len(on_site)
        if rows:
            rows[0]["current"] = True
            if is_today:
                changes = changes_since(date, rows[0]["entries"], on_site)
                self.mark_gone(date, rows[0]["entries"])
            else:
                stations = rows[0]["stations"]
        user = self.request.user
        lock = locks.held_by_other(user)
        context.update(
            date=date, batches=rows, changes=changes, view=view, is_today=is_today, stations=stations,
            can_arrange=can_arrange(user, date), can_create=can_arrange(user, date) and not lock,
            lock=lock, lock_minutes=StationEditLock.LOCK_MINUTES, can_force_unlock=bool(lock) and allows(user, "attendance-stations-unlock"),
            timeline=timeline(date) if view == "timeline" else None,
        )
        return context

    def mark_gone(self, date, entries):
        """目前生效的批次裡已經不在現場的人（下班、請假）標上離開時間，表格裡顯示成灰色。"""
        records = {r.employee_id: r for r in Attendance.objects.filter(date=date, employee_id__in=[e.employee_id for e in entries])}
        for entry in entries:
            record = records.get(entry.employee_id)
            entry.gone = not (record and record.on_site)
            entry.gone_at = record.clock_out if record else None


class StationCreateView(StationPageMixin, TemplateView):
    """建立安排：今天列出目前在場的人，之前的日期列出當天上過班的人；手動安排當日工位。
    改完先列出變更，確認後批次儲存並建立一筆批次紀錄。
    工位沒改、但名單和目前生效的批次不同（有人離開或新到）也算變更，可以建立新批次。
    同一時間只有一個帳號能編輯（編輯鎖）。"""

    template_name = "attendance/station_form.html"

    def build_rows(self, date, data=None):
        here = {"on_site": True} if date == timezone.localdate() else {"clock_in__isnull": False}
        records = (
            Attendance.objects.filter(date=date, **here)
            .select_related("employee", "station")
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
        self.date = self.get_date()
        rows, editable = self.build_rows(self.date)
        if not editable:
            raise PermissionDenied
        acquired, lock = locks.acquire(request.user, self.date)
        if not acquired:
            messages.warning(request, f"{self.locked_text(lock)}，請等對方完成後再編輯。")
            return self.redirect_back()
        return self.render_to_response(self.get_context_data(rows=rows, editable=editable))

    def post(self, request, *args, **kwargs):
        self.date = self.get_date()
        if request.POST.get("action") == "release":
            locks.release(request.user)
            return self.redirect_back()
        rows, editable = self.build_rows(self.date, data=request.POST)
        if not editable:
            raise PermissionDenied
        acquired, lock = locks.acquire(request.user, self.date)
        if not acquired:
            messages.error(request, f"{self.locked_text(lock)}，你的修改沒有儲存。")
            return self.redirect_back()
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
            locks.release(request.user)
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
                [StationBatchEntry(batch=batch, employee=row["record"].employee, station=row["form"].cleaned_data["station"]) for row in rows]
            )
        locks.release(request.user)
        roster = "、".join(text for text in (f"離開 {len(left)} 人" if left else "", f"新到 {len(arrived)} 人" if arrived else "") if text)
        messages.success(request, f"已建立安排，修改 {len(changes)} 人的工位{f'（名單{roster}）' if roster else ''}。")
        return self.redirect_back()

    def roster_changes(self, rows):
        """和目前生效的批次比，誰已經不在名單上、誰是新到的。當天還沒有批次時，所有人都算新到。"""
        latest = StationBatch.objects.filter(date=self.date).prefetch_related("entries__employee").first()
        before = {e.employee_id: e.employee for e in latest.entries.all()} if latest else {}
        now = {row["record"].employee_id for row in rows}
        left = [employee for pk, employee in before.items() if pk not in now]
        arrived = [row["record"].employee for row in rows if row["record"].employee_id not in before]
        return left, arrived

    @staticmethod
    def locked_text(lock):
        who = (lock.user.name or lock.user.username) if lock else "其他人"
        since = f"（{timezone.localtime(lock.started_at):%H:%M} 開始）" if lock else ""
        return f"{who} 正在編輯工位安排{since}"

    def redirect_back(self):
        return redirect(f"{reverse('attendance:stations')}?{urlencode({'date': f'{self.date:%Y-%m-%d}'})}")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stations = Station.objects.order_by("name")
        context.update(
            date=self.date, is_today=self.date == timezone.localdate(), stations=stations,
            lock_minutes=StationEditLock.LOCK_MINUTES,
        )
        return context


class StationLockView(StationPageMixin, View):
    """編輯鎖：編輯頁每分鐘呼叫一次延長（touch）、離開頁面時放開（release）；
    符合「強制解除編輯鎖」規則的人可以強制解除別人的鎖（force）。"""

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action == "release":
            locks.release(request.user)
            return JsonResponse({"ok": True})
        if action == "force":
            if not allows(request.user, "attendance-stations-unlock"):
                raise PermissionDenied
            lock = locks.current_lock()
            locks.release()
            if lock:
                messages.success(request, f"已解除 {lock.user.name or lock.user.username} 的編輯鎖。")
            return redirect(f"{reverse('attendance:stations')}?{urlencode({'date': request.POST.get('date', '')})}")
        form = DateForm(request.POST)
        date = form.cleaned_data["date"] if form.is_valid() and form.cleaned_data.get("date") else timezone.localdate()
        acquired, _ = locks.acquire(request.user, date)
        return JsonResponse({"ok": acquired})
