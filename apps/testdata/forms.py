from datetime import datetime, time

from django import forms
from django.utils import timezone

from apps.attendance.forms import TIME_FORMATS, time_input

from .catalog import load_catalog
from .generator import TYPES, TypeSetting

MAX_ORDERS = 20000  # 每種類型最多幾張，太多會讓網頁等很久
DEFAULT_COUNT = 100
SPLIT_KEYWORD = "無包裝"


def date_input():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def ratio_field(initial):
    return forms.DecimalField(
        min_value=0, max_digits=8, decimal_places=2, initial=initial, required=False,
        widget=forms.NumberInput(attrs={"step": "any", "class": "form-control form-control-sm text-end"}),
    )


def split_rows(platforms):
    """比例表的每一列：(顯示名稱, 平台, [(出貨類型, 範例訂單數), …])。
    出貨類型名稱有「無包裝」的另外拆成一列（例如「蝦皮購物（無包裝）」），可以單獨調比例；產生的資料平台名稱不變。"""
    for platform in platforms:
        split = [pair for pair in platform["ship_types"] if SPLIT_KEYWORD in pair[0]]
        rest = [pair for pair in platform["ship_types"] if SPLIT_KEYWORD not in pair[0]]
        if rest or not split:
            yield platform["name"], platform, rest
        if split:
            yield f"{platform['name']}（{SPLIT_KEYWORD}）", platform, split


def percents(pairs):
    total = sum(n for _, n in pairs) or 1
    return [(name, round(n * 100 / total, 2)) for name, n in pairs]


class GenerateForm(forms.Form):
    """4 種類型各自設定訂單數和下單時間的起訖；平台、出貨類型的比例全部類型共用；出貨類型有「無包裝」的另外拆一列。
    比例欄位的預設值是範例檔的實際比例（%），改的時候不用加到 100，照相對大小換算。"""

    first_order_no = forms.IntegerField(
        label="交易序號從", min_value=1,
        help_text="4 種類型接續編號。預設用現在的時間當開頭，每次生成都不一樣；要故意做出重複的訂單就填一樣的數字。",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = timezone.localtime()
        today = now.date()
        self.fields["first_order_no"].initial = int(now.strftime("%y%m%d%H%M")) * 100000

        self.type_rows = []
        for key, label in TYPES:
            self.fields[f"{key}_count"] = forms.IntegerField(
                min_value=0, max_value=MAX_ORDERS, initial=DEFAULT_COUNT,
                widget=forms.NumberInput(attrs={"class": "form-control form-control-sm text-end"}),
            )
            for part, initial in (("start", time(0, 0)), ("end", time(23, 59))):
                self.fields[f"{key}_{part}_date"] = forms.DateField(required=False, initial=today, widget=date_input())
                self.fields[f"{key}_{part}_time"] = forms.TimeField(
                    required=False, initial=initial, input_formats=TIME_FORMATS, widget=time_input()
                )
            self.type_rows.append((key, label, [self[f"{key}_{name}"] for name in
                                                ("count", "start_date", "start_time", "end_date", "end_time")]))

        self.platform_rows = []
        rows = list(split_rows(load_catalog()["platforms"]))
        for i, ((label, platform, pairs), percent) in enumerate(zip(rows, (p for _, p in percents(
                [(None, sum(n for _, n in pairs) or platform["orders"]) for _, platform, pairs in rows])))):
            self.fields[f"p{i}"] = ratio_field(percent)
            ship_types = []
            for j, (ship_type, type_percent) in enumerate(percents(pairs)):
                self.fields[f"p{i}_t{j}"] = ratio_field(type_percent)
                ship_types.append((ship_type, self[f"p{i}_t{j}"]))
            self.platform_rows.append((i, label, platform, self[f"p{i}"], ship_types))

    def clean(self):
        cleaned = super().clean()
        settings = []
        for key, label in TYPES:
            count = cleaned.get(f"{key}_count") or 0
            if not count:
                continue
            values = {part: (cleaned.get(f"{key}_{part}_date"), cleaned.get(f"{key}_{part}_time"))
                      for part in ("start", "end")}
            if not all(all(pair) for pair in values.values()):
                self.add_error(None, f"{label}：請填下單時間的開始、結束日期和時間。")
                continue
            start, end = (datetime.combine(*values[part]) for part in ("start", "end"))
            if end < start:
                self.add_error(None, f"{label}：結束時間要晚於開始時間。")
                continue
            settings.append(TypeSetting(key, label, count, start, end))
        if not settings and not self.errors:
            self.add_error(None, "至少要有一種類型的訂單數大於 0。")

        options = []
        for i, label, platform, field, ship_types in self.platform_rows:
            weight = float(cleaned.get(field.name) or 0)
            if not weight:
                continue
            types = {name: float(cleaned.get(f.name) or 0) for name, f in ship_types}
            if ship_types and not any(types.values()):
                self.add_error(None, f"{label}：平台比例大於 0，出貨類型的比例至少要有一個大於 0。")
            options.append((platform["name"], weight, types))
        if not options:
            self.add_error(None, "平台比例至少要有一個大於 0。")

        cleaned.update(settings=settings, options=options)
        return cleaned
