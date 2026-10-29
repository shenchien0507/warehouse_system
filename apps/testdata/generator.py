"""照設定產生假的訂單 Excel（歷史紀錄的 25 欄），打包成 zip。資料不寫進資料庫。

平台、出貨類型照設定的比例抽；店鋪、每張訂單的商品數、商品、數量隨機。
買家資料一律遮罩，出貨日期留空，出貨單號只有「正式訂單」才填。"""

import random
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO

from openpyxl import Workbook

from .catalog import load_catalog

COLUMNS = [
    "交易平台", "交易店鋪", "交易序號", "買家姓名", "出貨日期", "出貨類型", "商品編號", "商品名稱", "商品樣式",
    "小計數量", "建立時間", "會員交易筆數", "系統備註", "發票紀錄", "發票開立方式", "收件者姓名", "平台訂單編號",
    "出貨單號", "商品小計", "商品單價", "收件者手機", "收件者地址", "配送狀態", "配送狀態描述", "店家備註",
]
MASK = "****"
MASKED_COLUMNS = ("買家姓名", "收件者姓名", "收件者手機", "收件者地址")
TIME_FORMAT = "%Y/%m/%d %H:%M:%S"

# 4 種類型只是操作上分檔用，沒有特別意義；只有正式訂單會填出貨單號
TYPES = [("urgent", "急單"), ("shipping", "出貨中"), ("new", "新訂單"), ("formal", "正式訂單")]
WITH_SHIPMENT_NO = {"formal"}

# 每張訂單幾個商品、每個商品幾件：隨機，比例大致照範例
LINE_COUNTS = [(1, 32), (2, 23), (3, 11), (4, 9), (5, 6), (6, 5), (7, 4), (8, 3), (9, 3), (10, 4)]
QUANTITIES = [(1, 80), (2, 12), (3, 5), (4, 1), (5, 1), (6, 1)]
DEFAULT_SHIPMENT_SHAPE = "############"


@dataclass
class TypeSetting:
    key: str
    label: str
    count: int
    start: datetime
    end: datetime  # 含這一分鐘（到 :59 秒）


def weighted(rng, pairs):
    values, weights = zip(*pairs)
    return rng.choices(values, weights)[0]


def fill(rng, shape):
    return re.sub("#", lambda _: str(rng.randint(0, 9)), shape)


def random_time(rng, start, end):
    span = int((end - start).total_seconds()) + 59
    return start + timedelta(seconds=rng.randint(0, max(span, 0)))


def new_order(rng, catalog, platform, ship_type_weights, created, order_no):
    """一張假訂單（JSON 存得下的 dict）；建立時間只有日期的平台會改成當天 00:00:00。"""
    if platform["date_only"]:  # 範例裡這個平台的建立時間只有日期（00:00:00）
        created = created.replace(hour=0, minute=0, second=0)
    line_count = min(weighted(rng, LINE_COUNTS), len(catalog["products"]))
    return {
        "order_no": order_no,
        "platform": platform["name"],
        "shop": rng.choice(platform["shops"]) if platform["shops"] else "",
        "ship_type": weighted(rng, ship_type_weights),
        "created": created.strftime(TIME_FORMAT),
        "platform_order_no": fill(rng, rng.choice(platform["order_no_shapes"] or ["##############"])),
        "lines": [[code, name, spec, weighted(rng, QUANTITIES), price]
                  for code, name, spec, price in rng.sample(catalog["products"], line_count)],
    }


def new_shipment_no(rng, catalog, ship_type):
    return fill(rng, rng.choice(catalog["shipment_shapes"].get(ship_type) or [DEFAULT_SHIPMENT_SHAPE]))


def order_rows(order, shipment_no=""):
    for code, name, spec, quantity, price in order["lines"]:
        row = dict.fromkeys(COLUMNS, "")
        row.update({column: MASK for column in MASKED_COLUMNS})
        row.update({
            "交易平台": order["platform"], "交易店鋪": order["shop"], "交易序號": order["order_no"],
            "出貨類型": order["ship_type"], "商品編號": code, "商品名稱": name, "商品樣式": spec, "小計數量": quantity,
            "建立時間": order["created"], "平台訂單編號": order["platform_order_no"], "出貨單號": shipment_no,
            "商品小計": price * quantity, "商品單價": price,
        })
        yield [row[column] for column in COLUMNS]


def platform_choices(options, platforms):
    """options：[(平台, 比例, {出貨類型: 比例}), …] → weighted() 用的 [((平台, 出貨類型比例), 比例), …]"""
    return [((name, [(t, w) for t, w in types.items() if w > 0] or [("", 1)]), weight)
            for name, weight, types in options if weight > 0 and name in platforms]


def generate(settings, options, first_order_no, seed=None):
    """options：[(平台, 比例, {出貨類型: 比例}), …]，同一個平台可以有好幾列（例如無包裝另外一列）。
    比例照相對大小換算，不用加到 100。先照比例抽一列，再照那一列的出貨類型比例抽。
    回傳 {類型名稱: [列, …]}，交易序號從 first_order_no 起，4 種類型接續編號、不重複。"""
    rng = random.Random(seed)
    catalog = load_catalog()
    platforms = {p["name"]: p for p in catalog["platforms"]}
    choices = platform_choices(options, platforms)
    order_no = first_order_no
    result = {}
    for setting in settings:
        rows = []
        for _ in range(setting.count):
            platform, types = weighted(rng, choices)
            order = new_order(rng, catalog, platforms[platform], types,
                              random_time(rng, setting.start, setting.end), order_no)
            shipment_no = new_shipment_no(rng, catalog, order["ship_type"]) if setting.key in WITH_SHIPMENT_NO else ""
            rows.extend(order_rows(order, shipment_no))
            order_no += 1
        result[setting.label] = rows
    return result


def workbook_bytes(rows):
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Sheet1")
    ws.append(COLUMNS)
    for row in rows:
        ws.append(row)
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def zip_bytes(files, stamp):
    """files：{類型名稱: [列, …]}；沒有訂單的類型不放進 zip。"""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for label, rows in files.items():
            if rows:
                archive.writestr(f"{label}_{stamp}.xlsx", workbook_bytes(rows))
    return buffer.getvalue()
