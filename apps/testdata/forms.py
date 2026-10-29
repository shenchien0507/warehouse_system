from datetime import datetime, time, timedelta

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


def row_share(platform, pairs):
    """比例表一列的預設佔比：平台佔比 × 這一列的出貨類型在這個平台裡的比重（拆出無包裝時用）。"""
    total = sum(n for _, n in platform["ship_types"])
    return platform["share"] * sum(n for _, n in pairs) / total if total else platform["share"]


def percents(pairs):
    total = sum(n for _, n in pairs) or 1
    return [(name, round(n * 100 / total, 2)) for name, n in pairs]


class RatioFieldsMixin:
    """平台、出貨類型的比例欄位（測試資料產生、訂單流模擬共用）。
    預設值是範例檔的實際比例（%），改的時候不用加到 100，照相對大小換算；出貨類型有「無包裝」的另外拆一列。"""

    def add_ratio_fields(self):
        self.platform_rows = []
        rows = list(split_rows(load_catalog()["platforms"]))
        for i, ((label, platform, pairs), percent) in enumerate(zip(rows, (p for _, p in percents(
                [(None, row_share(platform, pairs)) for _, platform, pairs in rows])))):
            self.fields[f"p{i}"] = ratio_field(percent)
            ship_types = []
            for j, (ship_type, type_percent) in enumerate(percents(pairs)):
                self.fields[f"p{i}_t{j}"] = ratio_field(type_percent)
                ship_types.append((ship_type, self[f"p{i}_t{j}"]))
            self.platform_rows.append((i, label, platform, self[f"p{i}"], ship_types))

    def clean_ratios(self, cleaned):
        """回傳 [(平台, 比例, {出貨類型: 比例}), …]，給 generator 用。"""
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

        return options


class GenerateForm(RatioFieldsMixin, forms.Form):
    """4 種類型各自設定訂單數和下單時間的起訖；平台、出貨類型的比例全部類型共用。"""

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

        self.add_ratio_fields()

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

        cleaned.update(settings=settings, options=self.clean_ratios(cleaned))
        return cleaned


class SimulationStartForm(RatioFieldsMixin, forms.Form):
    """開始一個訂單流模擬。"""

    start_date = forms.DateField(label="從哪一天開始", widget=date_input())
    start_time = forms.TimeField(label="幾點開始", input_formats=TIME_FORMATS, widget=time_input())
    live = forms.TypedChoiceField(
        label="時間怎麼走", coerce=lambda v: v == "1", initial="0", widget=forms.RadioSelect,
        choices=[("0", "手動推進（自己把時間往前推，可以很快跑完一整天）"),
                 ("1", "跟著現在時間（每次打開或更新頁面，補上到現在為止流進來的單）")],
    )
    orders_per_day = forms.IntegerField(label="每天大約幾張單", min_value=1, max_value=MAX_ORDERS, initial=1000,
                                        help_text="照歷史紀錄每小時的曲線分布：凌晨少，晚上 20～23 點最多。")
    urgent_pct = forms.FloatField(label="抽到急單的比例（%）", min_value=0, max_value=100, initial=1)
    shipping_pct = forms.FloatField(label="抽到出貨中的比例（%）", min_value=0, max_value=100, initial=1)
    first_order_no = forms.IntegerField(label="交易序號從", min_value=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = timezone.localtime()
        self.fields["start_date"].initial = now.date()
        self.fields["start_time"].initial = time(0, 0)
        self.fields["first_order_no"].initial = int(now.strftime("%y%m%d%H%M")) * 100000
        self.add_ratio_fields()

    def clean(self):
        cleaned = super().clean()
        if (cleaned.get("urgent_pct") or 0) + (cleaned.get("shipping_pct") or 0) > 100:
            self.add_error(None, "急單、出貨中的比例加起來不能超過 100%。")
        if cleaned.get("start_date") and cleaned.get("start_time"):
            cleaned["start"] = datetime.combine(cleaned["start_date"], cleaned["start_time"])
            if cleaned["live"] and cleaned["start"] > timezone.localtime().replace(tzinfo=None):
                self.add_error("start_date", "跟著現在時間走的話，開始時間不能晚於現在。")
        cleaned["options"] = self.clean_ratios(cleaned)
        return cleaned


class AdvanceForm(forms.Form):
    """手動推進：推到指定時間，或按快速按鈕往前推幾分鐘。"""

    to_date = forms.DateField(required=False, widget=date_input())
    to_time = forms.TimeField(required=False, input_formats=TIME_FORMATS, widget=time_input())
    minutes = forms.IntegerField(required=False, min_value=1)

    def __init__(self, *args, clock=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.clock = clock
        if clock:
            self.fields["to_date"].initial = clock.date()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("minutes"):
            cleaned["to"] = self.clock + timedelta(minutes=cleaned["minutes"])
        elif cleaned.get("to_date") and cleaned.get("to_time"):
            cleaned["to"] = datetime.combine(cleaned["to_date"], cleaned["to_time"])
        else:
            raise forms.ValidationError("請填要推進到的日期和時間。")
        if cleaned["to"] <= self.clock:
            raise forms.ValidationError("要推進到的時間要晚於目前時間。")
        return cleaned


class ReleaseForm(forms.Form):
    count = forms.IntegerField(label="這輪出幾張", min_value=1, max_value=MAX_ORDERS,
                               widget=forms.NumberInput(attrs={"class": "form-control"}))
