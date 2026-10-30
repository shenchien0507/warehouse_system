from urllib.parse import quote

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import FormView, ListView, UpdateView

from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.tower.stats import kind_cards

from .forms import BulkEditFormSet, GridFormSet, KindRecordForm, QuickAddForm, kind_choices
from .models import Record
from .rules import can_edit, editable_records, kind_names


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


def chosen_kind(request):
    """網址 ?kind=隔日到 帶進來的種類（當日統計的卡片點進來）；不在選單裡的忽略。"""
    kind = request.GET.get("kind", "")
    return kind if kind in kind_names() else ""


class RecordListView(RecordPageMixin, ListView):
    """所有人的紀錄都看得到，最新的在最上面；?q= 用編號、名稱、日期或操作人搜尋。
    上方固定一列輸入（POST）：一次登記一筆，存好回到同一頁、輸入列清空；有錯留在原頁標紅。
    種類在輸入列最前面選，選好留在網址（?kind=），登記完還是同一個種類，連續登記不用再選。"""

    template_name = "records/list.html"
    paginate_by = 50

    def post(self, request, *args, **kwargs):
        form = QuickAddForm(request.POST)
        if form.is_valid():
            form.instance.created_by = request.user
            record = form.save()
            messages.success(request, f"已登記「{record}」。")
            return redirect(request.get_full_path())
        self.quick_form = form
        return self.get(request, *args, **kwargs)

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
        context["quick_form"] = getattr(self, "quick_form", None) or QuickAddForm(initial={"kind": chosen_kind(self.request)})
        day, cards = kind_cards()
        context.update(card_day=day, cards=cards, chosen=chosen_kind(self.request))
        context["rows"] = [{"record": r, "can_edit": can_edit(self.request.user, r)} for r in context["object_list"]]
        return context


class RecordGridView(RecordPageMixin, FormView):
    """像 Excel 的多列輸入：整列空白的略過，其他列全部正確才一起存，操作人是登入的帳號。"""

    template_name = "records/grid.html"
    form_class = GridFormSet

    def get_context_data(self, **kwargs):
        kind = self.request.POST.get("kind", "") if self.request.method == "POST" else chosen_kind(self.request)
        choices = kind_choices(kind)
        if kind_names():
            choices[0] = ("", "請先選種類")
        return super().get_context_data(kind_choices=choices, kind=kind, **kwargs)

    def get_success_url(self):
        return reverse("records:list") + (f"?kind={quote(self.kind)}" if self.kind else "")

    def form_valid(self, formset):
        rows = [form for form in formset if form.has_changed()]
        self.kind = self.request.POST.get("kind", "")
        names = kind_names()
        if names and self.kind not in names:
            messages.error(self.request, "請先選種類。" if not self.kind else "種類不在目前的統計分組裡。")
            return self.form_invalid(formset)
        if not rows:
            messages.error(self.request, "沒有輸入任何資料。")
            return self.form_invalid(formset)
        with transaction.atomic():
            for form in rows:
                form.instance.created_by = self.request.user
                form.instance.kind = self.kind
                form.save()
        messages.success(self.request, f"已登記 {len(rows)} 筆{f'（{self.kind}）' if self.kind else ''}。")
        return super().form_valid(formset)

    def form_invalid(self, formset):
        if any(formset.errors) or formset.non_form_errors():
            messages.error(self.request, "有欄位不正確，請檢查標紅的地方；這次全部都還沒存。")
        return super().form_invalid(formset)


def selected_ids(data):
    return [int(pk) for pk in data.getlist("ids") if pk.isdigit()]


class RecordBulkEditView(RecordPageMixin, FormView):
    """列表勾選的紀錄（?ids=1&ids=2…）用同樣的 Excel 表格一次修改；只列出自己可以改的，沒改的列不動。"""

    template_name = "records/grid.html"
    form_class = BulkEditFormSet
    success_url = reverse_lazy("records:list")

    def get_queryset(self):
        ids = selected_ids(self.request.GET)
        return editable_records(self.request.user).filter(pk__in=ids).order_by("number", "pk")

    def get(self, request, *args, **kwargs):
        if not self.get_queryset().exists():
            messages.error(request, "請先在列表勾選要修改的紀錄。")
            return redirect("records:list")
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "queryset": self.get_queryset()}

    def get_context_data(self, **kwargs):
        return super().get_context_data(bulk_edit=True, **kwargs)

    def form_valid(self, formset):
        changed = [form for form in formset if form.has_changed()]
        with transaction.atomic():
            for form in changed:
                form.instance.updated_by = self.request.user
                form.save()
        messages.success(self.request, f"已修改 {len(changed)} 筆。" if changed else "沒有任何變更。")
        return super().form_valid(formset)

    def form_invalid(self, formset):
        messages.error(self.request, "有欄位不正確，請檢查標紅的地方；這次全部都還沒存。")
        return super().form_invalid(formset)


class RecordBulkDeleteView(RecordPageMixin, View):
    """刪除列表勾選的紀錄；不能改的紀錄不會被刪。"""

    def post(self, request, *args, **kwargs):
        ids = selected_ids(request.POST)
        records = editable_records(request.user).filter(pk__in=ids)
        count = records.count()
        if count != len(set(ids)):
            raise PermissionDenied
        records.delete()
        messages.success(request, f"已刪除 {count} 筆。" if count else "沒有勾選任何紀錄。")
        return redirect(safe_next(request))


def safe_next(request):
    back = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        return reverse("records:list")
    return back


class RecordObjectMixin(RecordPageMixin):
    def get_object(self, queryset=None):
        record = get_object_or_404(Record, pk=self.kwargs["pk"])
        if not can_edit(self.request.user, record):
            raise PermissionDenied
        return record


class RecordEditView(RecordObjectMixin, UpdateView):
    template_name = "records/edit.html"
    form_class = KindRecordForm
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
        return redirect(safe_next(request))
