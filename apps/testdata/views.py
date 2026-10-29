"""「測試資料產生」：設定好之後按生成，直接下載 zip（每種類型一個 Excel）。不寫進資料庫。
這是暫時的功能，正式開發完成後整個 apps/testdata 移除（另外刪 settings、urls、選單各一行）。"""

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.generic import FormView

from apps.backoffice.menu import MENU_BY_KEY, can_use

from .forms import GenerateForm
from .generator import generate, zip_bytes


class GenerateView(FormView):
    page_key = "test-data"
    template_name = "testdata/generate.html"
    form_class = GenerateForm

    def dispatch(self, request, *args, **kwargs):
        if not can_use(request.user, MENU_BY_KEY[self.page_key]):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        data = form.cleaned_data
        files = generate(data["settings"], data["options"], data["first_order_no"])
        stamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        response = HttpResponse(zip_bytes(files, stamp), content_type="application/zip")
        response["Content-Disposition"] = content_disposition_header(True, f"測試資料_{stamp}.zip")
        return response
