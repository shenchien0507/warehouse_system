from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import FormView, UpdateView

from apps.backoffice.menu import MENU_BY_KEY, can_use

from .forms import EntryEditForm, ScanForm
from .models import Stage, WorkEntry
from .rules import can_edit, can_see_anomaly, scan

PAGE_KEYS = {Stage.PICKING: "worklog-picking", Stage.ALLOCATION: "worklog-allocation"}


class StagePageMixin:
    """網址裡的階段決定是撿貨還是配貨頁，兩頁各自有頁面權限。"""

    def dispatch(self, request, *args, **kwargs):
        self.stage = Stage(kwargs["stage"])
        self.menu_item = MENU_BY_KEY[PAGE_KEYS[self.stage]]
        if not can_use(request.user, self.menu_item):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def page_url(self):
        return reverse(f"worklog:{self.stage}")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(menu_item=self.menu_item, stage=self.stage, page_url=self.page_url())
        return context


class StagePageView(StagePageMixin, FormView):
    """最上面固定一列輸入，按 Enter 或「登記」後清空給下一個人用；下方是這個階段的紀錄，最新的在最上面。"""

    template_name = "worklog/page.html"
    form_class = ScanForm
    paginate_by = 50

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "stage": self.stage}

    def form_valid(self, form):
        entry, started = scan(self.stage, form.cleaned_data["number"], form.employee, self.request.user)
        employee = form.employee
        if started:
            text = f"{entry.number} 開始（{employee.employee_no} {employee.name}，{timezone.localtime(entry.started_at):%H:%M:%S}）"
            if entry.anomaly and can_see_anomaly(self.request.user):
                text += "；撿貨還沒刷結束，已標記異常"
        else:
            text = f"{entry.number} 結束（{employee.employee_no} {employee.name}，{timezone.localtime(entry.ended_at):%H:%M:%S}）"
        messages.success(self.request, text)
        return redirect(self.page_url())

    def form_invalid(self, form):
        for name in form.errors:
            form.fields[name].widget.attrs["class"] += " is-invalid"
        messages.error(self.request, "沒有登記：" + "；".join(e for errors in form.errors.values() for e in errors))
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        show_anomaly = self.stage == Stage.ALLOCATION and can_see_anomaly(self.request.user)
        entries = WorkEntry.objects.filter(stage=self.stage).select_related("start_employee", "end_employee", "updated_by")
        query = self.request.GET.get("q", "").strip()
        if query:
            entries = entries.filter(
                Q(number__icontains=query)
                | Q(start_employee__employee_no__icontains=query) | Q(start_employee__name__icontains=query)
                | Q(end_employee__employee_no__icontains=query) | Q(end_employee__name__icontains=query)
            )
        only_anomaly = show_anomaly and self.request.GET.get("anomaly") == "1"
        if only_anomaly:
            entries = entries.filter(anomaly=True)
        page = Paginator(entries, self.paginate_by).get_page(self.request.GET.get("page"))
        context.update(
            query=query, show_anomaly=show_anomaly, only_anomaly=only_anomaly,
            page_obj=page, is_paginated=page.has_other_pages(),
            rows=[self.row(e) for e in page],
        )
        return context

    def row(self, entry):
        if not can_edit(self.request.user, entry):
            return {"entry": entry}
        return {
            "entry": entry,
            "edit_url": reverse(f"worklog:{self.stage}_edit", args=[entry.pk]),
            "delete_url": reverse(f"worklog:{self.stage}_delete", args=[entry.pk]),
        }


def safe_next(request, fallback):
    back = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        return fallback
    return back


class EntryObjectMixin(StagePageMixin):
    def get_object(self, queryset=None):
        entry = get_object_or_404(WorkEntry, pk=self.kwargs["pk"], stage=self.stage)
        if not can_edit(self.request.user, entry):
            raise PermissionDenied
        return entry


class EntryEditView(EntryObjectMixin, UpdateView):
    template_name = "worklog/edit.html"
    form_class = EntryEditForm

    def get_success_url(self):
        return self.page_url()

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        messages.success(self.request, f"已修改「{form.instance}」。")
        return super().form_valid(form)


class EntryDeleteView(EntryObjectMixin, View):
    def post(self, request, *args, **kwargs):
        entry = self.get_object()
        entry.delete()
        messages.success(request, f"已刪除「{entry}」。")
        return redirect(safe_next(request, self.page_url()))
