"""後台「統計分組」：用版本管理分組條件，同時只有一個版本生效。"""

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.views.generic import FormView, TemplateView, View

from apps.backoffice.menu import can_use
from apps.backoffice.views import ManageDeleteView, ManageListView, ManageMixin

from .forms import ConditionFormSet, GroupVersionForm, SourceFileForm, StatGroupForm
from .importer import ImportFileError, read_combos
from .manage_views import localtime_text
from .models import GroupVersion, MappingVersion, StatGroup


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
            try:
                with transaction.atomic():
                    group = form.save()
                    formset.instance = group
                    formset.save()
            except IntegrityError:  # 同時送出兩次（例如連按儲存）時，另一次剛好先存了同名分組
                form.add_error("name", f"這個版本已經有叫「{form.cleaned_data['name']}」的分組了。")
                return self.render_to_response(self.get_context_data(form=form, formset=formset))
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
