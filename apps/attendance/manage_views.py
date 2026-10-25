"""到班的後台設定頁。"""

from django.contrib import messages
from django.shortcuts import redirect
from django.views.generic import UpdateView

from apps.backoffice.views import ManageMixin

from .forms import ClockSettingForm
from .models import ClockSetting


class ClockSettingUpdate(ManageMixin, UpdateView):
    """上下班時間：決定到班登記的「上班」「下班」按鈕什麼時候可以按。"""

    template_name = "backoffice/form.html"
    form_class = ClockSettingForm
    page_key = "manage-clock-setting"
    list_url_name = "attendance_manage:clock_setting"

    def get_object(self, queryset=None):
        return ClockSetting.load()

    def form_valid(self, form):
        setting = form.save()
        messages.success(
            self.request,
            f"已儲存。上班按鈕 {setting.describe('clock_in')} 可按，下班按鈕 {setting.describe('clock_out')} 可按，其餘時間請用補登。",
        )
        return redirect(self.get_success_url())
