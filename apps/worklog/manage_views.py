"""撿貨、配貨的後台設定頁。"""

from django import forms
from django.contrib import messages
from django.shortcuts import redirect
from django.views.generic import UpdateView

from apps.backoffice.views import ManageMixin

from .models import WorklogSetting


class WorklogSettingUpdate(ManageMixin, UpdateView):
    """重複刷的間隔，以及撿貨、配貨各自哪些工位的人可以登記。"""

    template_name = "worklog/setting_form.html"
    model = WorklogSetting
    fields = ["rescan_seconds", "picking_stations", "allocation_stations"]
    page_key = "manage-worklog-setting"
    list_url_name = "worklog_manage:setting"

    def get_object(self, queryset=None):
        return WorklogSetting.load()

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for name in ["picking_stations", "allocation_stations"]:
            form.fields[name].widget = forms.CheckboxSelectMultiple(choices=form.fields[name].choices)
            form.fields[name].queryset = form.fields[name].queryset.order_by("name")
        return form

    def form_valid(self, form):
        setting = form.save()
        if setting.rescan_seconds:
            text = f"已儲存。同一個編號刷完後 {setting.rescan_seconds} 秒內再刷會被擋下。"
        else:
            text = "已儲存。不限制重複刷的間隔。"
        for stage in ["picking", "allocation"]:
            names = "、".join(s.name for s in setting.stations_for(stage))
            label = "撿貨" if stage == "picking" else "配貨"
            text += f"{label}：{'只有工位「' + names + '」的人可以登記' if names else '不限工位'}。"
        messages.success(self.request, text)
        return redirect(self.get_success_url())
