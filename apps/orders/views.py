"""後台「匯入欄位對應」：用版本管理欄位對應，同時只有一個版本生效。
「訂單統計」：匯入檔案，每一批獨立統計。"""

from django.contrib import messages
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.views.generic import DetailView, FormView, ListView, TemplateView, View

from apps.backoffice.menu import MENU_BY_KEY, can_use
from apps.backoffice.views import ManageDeleteView, ManageListView, ManageMixin

from .batches import import_file
from .forms import (
    CheckFileForm, ConditionFormSet, GroupVersionForm, ImportForm, MappingForm, SourceFileForm, StatGroupForm, UploadForm,
)
from .importer import ImportFileError, inspect, read_combos, read_headers
from .models import GroupVersion, ImportBatch, MappingVersion, StatGroup
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
    queryset = ImportBatch.objects.select_related("imported_by", "mapping_version", "group_version")
    paginate_by = 20

    def post(self, request, *args, **kwargs):
        form = ImportForm(request.POST, request.FILES)
        if form.is_valid():
            outcome = import_file(request.user, form.cleaned_data["file"], form.cleaned_data["work_date"])
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
        context["active_groups"] = GroupVersion.active()
        return context


class BatchDetailView(StatsPageMixin, DetailView):
    template_name = "orders/batch_detail.html"
    queryset = ImportBatch.objects.select_related("imported_by", "mapping_version", "group_version")
    context_object_name = "batch"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        summary = batch_stats(self.object)
        context["summary"] = summary
        context["by_import_time"] = len(summary.by_import_time)
        dated = [day for day in summary.days if day]
        context["first_day"], context["last_day"] = (dated[0], dated[-1]) if dated else (None, None)
        return context


class BatchDeleteView(StatsPageMixin, View):
    """匯入錯檔案時刪掉整批。"""

    def post(self, request, *args, **kwargs):
        batch = get_object_or_404(ImportBatch, pk=kwargs["pk"])
        name = str(batch)
        batch.delete()
        messages.success(request, f"已刪除匯入批次 {name}。")
        return redirect("orders:batch_list")


class GroupVersionMixin:
    model = GroupVersion
    page_key = "manage-order-groups"
    list_url_name = "orders_manage:group_version_list"


def describe_cutoff(group):
    if not group.cutoff:
        return "不分（一天一列）" if group.split_by_day else "不分（跨日合計）"
    notes = [text for on, text in [(group.carry_over, "作業日之前算前"), (group.midnight_uses_import_time, "00:00:00 用匯入時間")] if on]
    text = group.cutoff.strftime("%H:%M")
    return f"{text}（{'、'.join(notes)}）" if notes else text


class GroupVersionList(GroupVersionMixin, ManageListView):
    queryset = GroupVersion.objects.select_related("created_by").prefetch_related("groups")
    columns = [
        ("版本", str),
        ("狀態", "status"),
        ("分組", lambda o: "、".join(g.name for g in o.groups.all())),
        ("建立人", lambda o: o.created_by.name if o.created_by else ""),
        ("建立時間", lambda o: localtime_text(o.created_at)),
        ("第一次生效", lambda o: localtime_text(o.activated_at)),
        ("備註", "note"),
    ]

    create_url_name = "orders_manage:group_version_create"

    def row_actions(self, obj):
        actions = [("編輯" if not obj.is_locked else "查看", reverse("orders_manage:group_version_detail", args=[obj.pk]), "primary")]
        if not obj.is_locked:
            actions.append(("刪除", reverse("orders_manage:group_version_delete", args=[obj.pk]), "danger"))
        return actions

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["note"] = (
            "統計分組和欄位對應一樣用版本管理：同時只有一個版本生效，匯入時用生效中的版本，每個批次會記住用的版本，之後改分組不影響舊批次。"
            "生效過的版本不能再改。按「新增」建立空白版本從頭設定，或在版本頁按「複製成新版本」沿用現有分組，改好再按「生效」。"
        )
        return context


def load_combos(form):
    """讀上傳的來源檔，回傳組合；讀不到時把錯誤加到表單上並回傳 None。"""
    mapping = MappingVersion.active()
    if mapping is None:
        form.add_error("file", "目前沒有生效的欄位對應版本，請先到「匯入欄位對應」設定。")
        return None
    try:
        return read_combos(mapping, form.cleaned_data["file"])
    except ImportFileError as exc:
        form.add_error("file", str(exc))
        return None


class GroupVersionCreate(GroupVersionMixin, ManageMixin, FormView):
    """新增空白草稿版本：上傳來源檔讀出選項，再從零開始設定分組。"""

    template_name = "backoffice/form.html"
    form_class = GroupVersionForm

    def form_valid(self, form):
        combos = load_combos(form)
        if combos is None:
            return self.form_invalid(form)
        version = GroupVersion.objects.create(
            number=GroupVersion.next_number(), note=form.cleaned_data["note"], created_by=self.request.user,
            source_file_name=form.cleaned_data["file"].name[:200], source_combos=combos,
        )
        messages.success(self.request, f"已建立 {version}（空白草稿），從來源檔讀到 {len(combos)} 種平台／店鋪／出貨類型組合。請新增分組，改好後按「生效」。")
        return redirect("orders_manage:group_version_detail", pk=version.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object"] = None
        return context


class GroupVersionObjectMixin(GroupVersionMixin, ManageMixin):
    @cached_property
    def version(self):
        return get_object_or_404(GroupVersion, pk=self.kwargs["version_pk"] if "version_pk" in self.kwargs else self.kwargs["pk"])


class GroupVersionDetail(GroupVersionObjectMixin, TemplateView):
    """版本裡的分組：草稿可以新增、編輯、刪除分組；生效過的只能看。"""

    template_name = "orders/group_version_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        version = self.version
        context["object"] = version
        context["active"] = GroupVersion.active()
        context["source_form"] = SourceFileForm()
        context["platform_count"] = len({c[0] for c in version.source_combos if c[0]})
        context["groups"] = [
            {"group": g, "conditions": [c.describe() for c in g.conditions.all()], "cutoff": describe_cutoff(g)}
            for g in version.groups.prefetch_related("conditions")
        ]
        return context


class GroupVersionSource(GroupVersionObjectMixin, View):
    """草稿重新上傳來源檔，更新條件的選項。"""

    def post(self, request, *args, **kwargs):
        version = self.version
        if version.is_locked:
            messages.error(request, f"{version} 生效過，不能再改。請按「複製成新版本」再修改。")
            return redirect("orders_manage:group_version_detail", pk=version.pk)
        form = SourceFileForm(request.POST, request.FILES)
        combos = load_combos(form) if form.is_valid() else None
        if combos is None:
            messages.error(request, "；".join(form.errors.get("file", ["請選擇檔案。"])))
        else:
            version.source_file_name, version.source_combos = form.cleaned_data["file"].name[:200], combos
            version.save(update_fields=["source_file_name", "source_combos"])
            messages.success(request, f"已更新 {version} 的來源檔，讀到 {len(combos)} 種組合。")
        return redirect("orders_manage:group_version_detail", pk=version.pk)


class GroupVersionActivate(GroupVersionObjectMixin, View):
    def post(self, request, *args, **kwargs):
        version = self.version
        if not version.groups.exists():
            messages.error(request, f"{version} 還沒有任何分組，不能生效。")
        else:
            version.activate()
            messages.success(request, f"{version} 已生效，之後匯入的批次都用這個版本統計。")
        return redirect("orders_manage:group_version_detail", pk=version.pk)


class GroupVersionCopy(GroupVersionObjectMixin, View):
    def post(self, request, *args, **kwargs):
        new = self.version.copy(request.user)
        messages.success(request, f"已從 {self.version} 複製成 {new}（草稿）。")
        return redirect("orders_manage:group_version_detail", pk=new.pk)


class GroupVersionDelete(GroupVersionMixin, ManageDeleteView):
    """只能刪除沒生效過的草稿。"""

    queryset = GroupVersion.objects.filter(activated_at__isnull=True)


class DraftGroupMixin(GroupVersionObjectMixin):
    """分組的新增、編輯、刪除只能在草稿版本裡做。"""

    def dispatch(self, request, *args, **kwargs):
        if can_use(request.user, self.menu_item) and self.version.is_locked:
            messages.error(request, f"{self.version} 生效過，不能再改。請按「複製成新版本」再修改。")
            return redirect("orders_manage:group_version_detail", pk=self.version.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("orders_manage:group_version_detail", args=[self.version.pk])


class GroupFormView(DraftGroupMixin, FormView):
    """分組本身的欄位和底下的條件一起存。條件的選項來自版本的來源檔，要先上傳。"""

    def get(self, request, *args, **kwargs):
        if not self.version.source_combos:
            messages.warning(request, f"{self.version} 還沒有來源檔，請先上傳來源檔，條件才有選項。")
            return redirect(self.get_success_url())
        return super().get(request, *args, **kwargs)

    template_name = "orders/group_form.html"
    form_class = StatGroupForm
    group = None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.group or StatGroup(version=self.version)
        return kwargs

    def get_formset(self):
        data = self.request.POST if self.request.method == "POST" else None
        return ConditionFormSet(data, instance=self.group or StatGroup(version=self.version), prefix="conditions")

    def post(self, request, *args, **kwargs):
        form, formset = self.get_form(), self.get_formset()
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                group = form.save()
                formset.instance = group
                formset.save()
            messages.success(request, f"已儲存分組「{group}」。")
            return redirect(self.get_success_url())
        return self.render_to_response(self.get_context_data(form=form, formset=formset))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["version"] = self.version
        context["object"] = self.group
        context["formset"] = kwargs.get("formset") or self.get_formset()
        context["list_url"] = self.get_success_url()
        context["combos"] = self.version.source_combos
        return context


class GroupCreate(GroupFormView):
    pass


class GroupUpdate(GroupFormView):
    @cached_property
    def group(self):
        return get_object_or_404(StatGroup, pk=self.kwargs["pk"], version=self.version)


class GroupDelete(DraftGroupMixin, View):
    def post(self, request, *args, **kwargs):
        group = get_object_or_404(StatGroup, pk=kwargs["pk"], version=self.version)
        group.delete()
        messages.success(request, f"已刪除分組「{group.name}」。")
        return redirect(self.get_success_url())
