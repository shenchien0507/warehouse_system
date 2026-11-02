"""撿貨、配貨的後台設定頁。"""

from django.contrib import messages
from django.shortcuts import redirect
from django.views.generic import UpdateView

from apps.backoffice.views import ManageMixin

from .models import WorklogSetting


class WorklogSettingUpdate(ManageMixin, UpdateView):
    """重複刷的間隔：同一個編號刷完後幾秒內再刷不算。"""

    template_name = "backoffice/form.html"
    model = WorklogSetting
    fields = ["rescan_seconds"]
    page_key = "manage-worklog-setting"
    list_url_name = "worklog_manage:setting"

    def get_object(self, queryset=None):
        return WorklogSetting.load()

    def form_valid(self, form):
        setting = form.save()
        if setting.rescan_seconds:
            text = f"已儲存。同一個編號刷完後 {setting.rescan_seconds} 秒內再刷會被擋下。"
        else:
            text = "已儲存。不限制重複刷的間隔。"
        messages.success(self.request, text)
        return redirect(self.get_success_url())
