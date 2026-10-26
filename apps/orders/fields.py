"""系統自己的訂單欄位：匯入時來源檔的欄名都對應到這些欄位。

key 是程式與資料庫用的代碼，label 只是畫面上顯示的中文。
來源檔改欄名只要到後台「匯入欄位對應」新增版本，不用改這裡；要讓系統多記一種資料才在 FIELDS 加一筆。
只列系統用得到的資料：買家個資、發票、金額、配送狀態、備註都不列，匯入時也不保存。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderField:
    key: str
    label: str
    kind: str  # text、int、datetime，決定匯入時怎麼轉換
    must_map: bool = False  # 版本一定要選到來源欄才能生效；值能不能空白由之後各功能自己決定
    help: str = ""


KIND_LABELS = {"text": "文字", "int": "整數", "datetime": "日期時間"}

FIELDS = [
    OrderField("order_no", "訂單號", "text", must_map=True, help="同一張訂單的多列商品用它合併，一定要選"),
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
]

FIELDS_BY_KEY = {f.key: f for f in FIELDS}
FIELD_CHOICES = [(f.key, f.label) for f in FIELDS]
