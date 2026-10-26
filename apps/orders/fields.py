"""系統自己的訂單欄位：匯入時來源檔的欄名都對應到這些欄位。

來源檔改欄名只要到後台「匯入欄位對應」改對應，不用改這裡；要讓系統多記一種資料才在 FIELDS 加一筆。
買家姓名、電話、地址刻意不列，系統不保存個資。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderField:
    key: str
    label: str
    kind: str  # text、int、datetime，決定匯入時怎麼轉換
    always_required: bool = False
    help: str = ""


KIND_LABELS = {"text": "文字", "int": "整數", "datetime": "日期時間"}

FIELDS = [
    OrderField("order_no", "訂單號", "text", always_required=True, help="同一張訂單的多列商品用它合併"),
    OrderField("platform_order_no", "平台訂單編號", "text"),
    OrderField("platform", "平台", "text"),
    OrderField("shop", "店鋪", "text"),
    OrderField("order_time", "下單時間", "datetime"),
    OrderField("ship_time", "出貨時間", "datetime"),
    OrderField("ship_type", "出貨方式", "text"),
    OrderField("shipment_no", "出貨單號", "text"),
    OrderField("product_code", "商品編號", "text"),
    OrderField("product_name", "商品名稱", "text"),
    OrderField("product_spec", "商品樣式", "text"),
    OrderField("quantity", "數量", "int"),
    OrderField("delivery_status", "配送狀態", "text"),
]

FIELDS_BY_KEY = {f.key: f for f in FIELDS}
FIELD_CHOICES = [(f.key, f.label) for f in FIELDS]
