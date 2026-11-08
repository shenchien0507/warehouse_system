"""撿貨、配貨的後台設定頁。"""

from django import forms
from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import UpdateView

from apps.backoffice.views import ManageMixin

from .models import WorklogSetting


class WorklogSettingUpdate(ManageMixin, UpdateView):
    """重複刷的間隔，以及撿貨、配貨各自哪些工位的人可以登記。"""

    template_name = "worklog/setting_form.html"
    model = WorklogSetting
    fields = ["rescan_seconds", "carry_start", "picking_stations", "allocation_stations"]
    page_key = "manage-worklog-setting"
    list_url_name = "worklog_manage:setting"

    def get_object(self, queryset=None):
        return WorklogSetting.load()

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for name in ["picking_stations", "allocation_stations"]:
            form.fields[name].widget = forms.CheckboxSelectMultiple(choices=form.fields[name].choices)
            form.fields[name].queryset = form.fields[name].queryset.order_by("name")
        form.fields["carry_start"].widget = forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d")
        return form

    def form_valid(self, form):
        start = form.cleaned_data.get("carry_start")
        if "carry_start" in form.changed_data and start and start < timezone.localdate():
            # 設成過去的日期，那天以後的每一天都還沒日結，作業日會退回那天，要一天一天日結
            form.add_error("carry_start", "結轉起算日不能早於今天。要重新歸零請填今天。")
            return self.form_invalid(form)
        return self.save_setting(form)

    def save_setting(self, form):
        setting = form.save()
        if setting.rescan_seconds:
            text = f"已儲存。同一個編號刷完後 {setting.rescan_seconds} 秒內再刷會被擋下。"
        else:
            text = "已儲存。不限制重複刷的間隔。"
        for stage in ["picking", "allocation"]:
            names = "、".join(s.name for s in setting.stations_for(stage))
            label = "撿貨" if stage == "picking" else "配貨"
            text += f"{label}：{'只有工位「' + names + '」的人可以登記' if names else '不限工位'}。"
        text += f"結轉從 {setting.carry_start:%Y/%m/%d} 起算，每天要日結。" if setting.carry_start else "不結轉，作業日就是系統日期。"
        messages.success(self.request, text)
        return redirect(self.get_success_url())
