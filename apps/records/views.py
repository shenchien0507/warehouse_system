from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import FormView, ListView, UpdateView

from apps.backoffice.menu import MENU_BY_KEY, can_use

from .forms import GridFormSet, RecordForm
from .models import Record
from .rules import can_edit


class RecordPageMixin:
    page_key = "records"

    def dispatch(self, request, *args, **kwargs):
        if not can_use(request.user, MENU_BY_KEY[self.page_key]):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_item"] = MENU_BY_KEY[self.page_key]
        return context


class RecordListView(RecordPageMixin, ListView):
    """所有人的紀錄都看得到，最新的在最上面；?q= 用編號、名稱、日期或操作人搜尋。"""

    template_name = "records/list.html"
    paginate_by = 50

    def get_queryset(self):
        records = Record.objects.select_related("created_by", "updated_by")
        self.query = self.request.GET.get("q", "").strip()
        if self.query:
            records = records.filter(
                Q(number__icontains=self.query) | Q(name__icontains=self.query) | Q(date_text__icontains=self.query)
                | Q(created_by__username__icontains=self.query) | Q(created_by__name__icontains=self.query)
            )
        return records

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["query"] = self.query
        context["rows"] = [{"record": r, "can_edit": can_edit(self.request.user, r)} for r in context["object_list"]]
        return context


class RecordGridView(RecordPageMixin, FormView):
    """像 Excel 的多列輸入：整列空白的略過，其他列全部正確才一起存，操作人是登入的帳號。"""

    template_name = "records/grid.html"
    form_class = GridFormSet
    success_url = reverse_lazy("records:list")

    def form_valid(self, formset):
        rows = [form for form in formset if form.has_changed()]
        if not rows:
            messages.error(self.request, "沒有輸入任何資料。")
            return self.form_invalid(formset)
        with transaction.atomic():
            for form in rows:
                form.instance.created_by = self.request.user
                form.save()
        messages.success(self.request, f"已登記 {len(rows)} 筆。")
        return super().form_valid(formset)

    def form_invalid(self, formset):
        if any(formset.errors) or formset.non_form_errors():
            messages.error(self.request, "有欄位不正確，請檢查標紅的地方；這次全部都還沒存。")
        return super().form_invalid(formset)


class RecordObjectMixin(RecordPageMixin):
    def get_object(self, queryset=None):
        record = get_object_or_404(Record, pk=self.kwargs["pk"])
        if not can_edit(self.request.user, record):
            raise PermissionDenied
        return record


class RecordEditView(RecordObjectMixin, UpdateView):
    template_name = "records/edit.html"
    form_class = RecordForm
    success_url = reverse_lazy("records:list")

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        messages.success(self.request, f"已修改「{form.instance}」。")
        return super().form_valid(form)


class RecordDeleteView(RecordObjectMixin, View):
    def post(self, request, *args, **kwargs):
        record = self.get_object()
        record.delete()
        messages.success(request, f"已刪除「{record}」。")
        back = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
            back = "records:list"
        return redirect(back)
