"""後台「匯入欄位對應」：用版本管理欄位對應，同時只有一個版本生效。
「訂單統計」：匯入檔案，每一批獨立統計。"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.views.generic import DetailView, FormView, ListView, View

from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.backoffice.views import ManageDeleteView, ManageListView, ManageMixin

from .batches import import_file
from .forms import CheckFileForm, ImportForm, MappingForm, UploadForm
from .importer import ImportFileError, inspect, read_headers
from .models import ImportBatch, MappingVersion
from .stats import batch_stats


def localtime_text(value):
    return timezone.localtime(value).strftime("%Y/%m/%d %H:%M") if value else ""


class VersionMixin:
    model = MappingVersion
    page_key = "manage-order-import"
    list_url_name = "orders_manage:version_list"


class VersionList(VersionMixin, ManageListView):
    queryset = MappingVersion.objects.select_related("created_by").prefetch_related("mappings")
    columns = [
        ("版本", str),
        ("狀態", "status"),
        ("來源檔", "source_file_name"),
        ("已對應欄位", lambda o: len(o.mappings.all())),
        ("建立人", lambda o: o.created_by.name if o.created_by else ""),
        ("建立時間", lambda o: localtime_text(o.created_at)),
        ("第一次生效", lambda o: localtime_text(o.activated_at)),
        ("備註", "note"),
    ]
    create_url_name = "orders_manage:version_create"

    def row_actions(self, obj):
        actions = [("編輯" if not obj.is_locked else "查看", reverse("orders_manage:version_detail", args=[obj.pk]), "primary")]
        if not obj.is_locked:
            actions.append(("刪除", reverse("orders_manage:version_delete", args=[obj.pk]), "danger"))
        return actions

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["note"] = (
            "同時只有一個版本生效。來源檔的欄名改了，按「新增」上傳新的來源檔建立新版本，選好對應後按「生效」。"
            "生效過的版本不能再改，舊版本會保留，可以隨時切回去。"
        )
        return context


class VersionCreate(VersionMixin, ManageMixin, FormView):
    """上傳來源檔讀出欄名，建立草稿版本；目前生效版本裡、新檔也有的欄名會自動帶入。"""

    template_name = "backoffice/form.html"
    form_class = UploadForm

    def get_initial(self):
        active = MappingVersion.active()
        return {"header_row": active.header_row if active else 1}

    def form_valid(self, form):
        upload = form.cleaned_data["file"]
        try:
            headers = read_headers(upload, form.cleaned_data["header_row"])
        except ImportFileError as exc:
            form.add_error("file", str(exc))
            return self.form_invalid(form)
        if not headers:
            form.add_error("header_row", "這一列沒有欄名，請確認欄名在第幾列。")
            return self.form_invalid(form)
        version = MappingVersion.objects.create(
            number=MappingVersion.next_number(), header_row=form.cleaned_data["header_row"],
            source_file_name=upload.name, source_columns=headers, created_by=self.request.user,
        )
        active = MappingVersion.active()
        if active:
            version.set_mappings({k: v for k, v in active.mapping_dict().items() if v in headers})
            version.note = f"依 {active} 帶入對應"
            version.save(update_fields=["note"])
        messages.success(self.request, f"已建立 {version}（草稿），讀到 {len(headers)} 個欄名。請選好對應後按「儲存」，再按「生效」。")
        return redirect("orders_manage:version_detail", pk=version.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object"] = None
        return context


class VersionObjectMixin(VersionMixin, ManageMixin):
    @cached_property
    def object(self):
        return get_object_or_404(MappingVersion, pk=self.kwargs["pk"])


class VersionDetail(VersionObjectMixin, FormView):
    """草稿可以改對應；生效過的版本只能看。也可以上傳檔案用這個版本試讀。"""

    template_name = "orders/version_detail.html"
    form_class = MappingForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["version"] = self.object
        return kwargs

    def post(self, request, *args, **kwargs):
        if self.object.is_locked:
            messages.error(request, f"{self.object} 生效過，不能再改。請按「複製成新版本」再修改。")
            return redirect("orders_manage:version_detail", pk=self.object.pk)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        form.save()
        messages.success(self.request, f"{self.object} 已儲存。")
        return redirect("orders_manage:version_detail", pk=self.object.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object"] = self.object
        context["active"] = MappingVersion.active()
        context["missing_must_map"] = self.object.missing_must_map()
        context["check_form"] = kwargs.get("check_form") or CheckFileForm()
        return context


class VersionCheck(VersionDetail):
    """上傳檔案用這個版本試讀前 500 列，結果顯示在版本頁，不存訂單。"""

    def post(self, request, *args, **kwargs):
        check_form = CheckFileForm(request.POST, request.FILES)
        context = {"check_form": check_form, "form": MappingForm(version=self.object)}
        if check_form.is_valid():
            upload = check_form.cleaned_data["file"]
            try:
                context["result"] = inspect(self.object, upload)
                context["file_name"] = upload.name
            except ImportFileError as exc:
                check_form.add_error("file", str(exc))
        return self.render_to_response(self.get_context_data(**context))


class VersionActivate(VersionObjectMixin, View):
    def post(self, request, *args, **kwargs):
        version = self.object
        missing = version.missing_must_map()
        if missing:
            messages.error(request, f"{version} 還沒選來源欄：{'、'.join(f.label for f in missing)}，不能生效。")
        else:
            version.activate()
            messages.success(request, f"{version} 已生效，之後匯入都用這個版本。")
        return redirect("orders_manage:version_detail", pk=version.pk)


class VersionCopy(VersionObjectMixin, View):
    def post(self, request, *args, **kwargs):
        new = self.object.copy(request.user)
        messages.success(request, f"已從 {self.object} 複製成 {new}（草稿）。")
        return redirect("orders_manage:version_detail", pk=new.pk)


class VersionDelete(VersionMixin, ManageDeleteView):
    """只能刪除沒生效過的草稿。"""

    queryset = MappingVersion.objects.filter(activated_at__isnull=True)


class StatsPageMixin:
    page_key = "order-stats"

    def dispatch(self, request, *args, **kwargs):
        if not can_use(request.user, MENU_BY_KEY[self.page_key]):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_item"] = MENU_BY_KEY[self.page_key]
        return context


class BatchListView(StatsPageMixin, ListView):
    """匯入檔案與歷次匯入紀錄；匯入成功就直接到這一批的統計。"""

    template_name = "orders/batch_list.html"
    queryset = ImportBatch.objects.select_related("imported_by", "mapping_version")
    paginate_by = 20

    def post(self, request, *args, **kwargs):
        form = ImportForm(request.POST, request.FILES)
        if form.is_valid():
            outcome = import_file(request.user, form.cleaned_data["file"])
            if outcome.batch:
                messages.success(request, f"已匯入 {outcome.batch.file_name}：{outcome.batch.line_count} 列、{outcome.batch.order_count} 張訂單。")
                return redirect("orders:batch_detail", pk=outcome.batch.pk)
            form.add_error("file", outcome.message)
            self.outcome = outcome
        self.form = form
        return self.get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = getattr(self, "form", None) or ImportForm()
        context["outcome"] = getattr(self, "outcome", None)
        context["active_version"] = MappingVersion.active()
        return context


class BatchDetailView(StatsPageMixin, DetailView):
    template_name = "orders/batch_detail.html"
    queryset = ImportBatch.objects.select_related("imported_by", "mapping_version")
    context_object_name = "batch"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = batch_stats(self.object)
        context["rows"] = rows
        context["total_distinct"] = self.object.order_count
        return context


class BatchDeleteView(StatsPageMixin, View):
    """匯入錯檔案時刪掉整批。"""

    def post(self, request, *args, **kwargs):
        batch = get_object_or_404(ImportBatch, pk=kwargs["pk"])
        name = str(batch)
        batch.delete()
        messages.success(request, f"已刪除匯入批次 {name}。")
        return redirect("orders:batch_list")
