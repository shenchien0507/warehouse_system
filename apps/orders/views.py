"""後台「匯入欄位對應」：管理匯入範本，並上傳檔案測試對應結果。"""

from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.functional import cached_property
from django.views.generic import FormView

from apps.backoffice.views import ManageCreateView, ManageDeleteView, ManageListView, ManageMixin, ManageUpdateView

from .forms import ImportTemplateForm, TestFileForm
from .importer import ImportFileError, inspect
from .models import ImportTemplate


class TemplateMixin:
    model = ImportTemplate
    form_class = ImportTemplateForm
    page_key = "manage-order-import"
    list_url_name = "orders_manage:template_list"


class TemplateList(TemplateMixin, ManageListView):
    queryset = ImportTemplate.objects.prefetch_related("mappings")
    columns = [
        ("範本名稱", "name"),
        ("欄名在第幾列", "header_row"),
        ("已對應欄位", lambda o: len(o.mappings.all())),
        ("備註", "note"),
        ("更新時間", lambda o: o.updated_at.strftime("%Y/%m/%d %H:%M")),
    ]
    create_url_name = "orders_manage:template_create"
    edit_url_name = "orders_manage:template_edit"
    delete_url_name = "orders_manage:template_delete"

    def row_actions(self, obj):
        return [("測試檔案", reverse("orders_manage:template_test", args=[obj.pk]), "success")] + super().row_actions(obj)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["note"] = "來源檔的欄名改了，只要編輯範本、改「來源欄名」就能繼續匯入。改完可以按「測試檔案」上傳一份檔案確認。"
        return context


class TemplateFormMixin(TemplateMixin):
    template_name = "orders/template_form.html"


class TemplateCreate(TemplateFormMixin, ManageCreateView):
    pass


class TemplateUpdate(TemplateFormMixin, ManageUpdateView):
    def get_success_url(self):
        return reverse("orders_manage:template_edit", args=[self.object.pk])


class TemplateDelete(TemplateMixin, ManageDeleteView):
    pass


class TemplateTest(TemplateMixin, ManageMixin, FormView):
    """上傳一份檔案，看範本找得到哪些欄、前幾列轉換成什麼樣子；不存訂單。"""

    template_name = "orders/template_test.html"
    form_class = TestFileForm

    @cached_property
    def object(self):
        return get_object_or_404(ImportTemplate, pk=self.kwargs["pk"])

    def form_valid(self, form):
        try:
            result = inspect(self.object, form.cleaned_data["file"])
        except ImportFileError as exc:
            form.add_error("file", str(exc))
            return self.form_invalid(form)
        self.object.known_columns = [h for h in result.headers if h]
        self.object.save(update_fields=["known_columns", "updated_at"])
        return self.render_to_response(self.get_context_data(form=form, result=result, file_name=form.cleaned_data["file"].name))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object"] = self.object
        return context
