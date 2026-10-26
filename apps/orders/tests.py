from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from apps.accounts.models import PagePermission
from apps.accounts.testing import Level, make_user

from .models import FieldMapping, ImportTemplate

HEADERS = ["交易平台", "交易序號", "買家姓名", "出貨日期", "商品編號", "小計數量", "建立時間"]
ROWS = [
    ["蝦皮購物", 13132187, "王小明", "2026/08/10 11:06:41", "DO479", 12, "2026/08/07 00:40:29"],
    ["蝦皮購物", 13132187, "王小明", "2026/08/10 11:06:41", "DR312", 1, "2026/08/07 00:40:29"],
    ["friDay商城", 10035943, "陳秀貞", "2026/08/10 11:35:15", "DO528", 1, "2026/08/07 00:00:00"],
]


def xlsx(headers=HEADERS, rows=ROWS, name="匯出.xlsx", title_rows=0):
    wb = Workbook()
    ws = wb.active
    for _ in range(title_rows):
        ws.append(["報表標題"])
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buffer = BytesIO()
    wb.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


def form_data(**overrides):
    data = {"name": "測試範本", "header_row": 1, "note": "", "src_order_no": "交易序號"}
    data.update(overrides)
    return data


class OrderImportTestCase(TestCase):
    def setUp(self):
        self.client.login(username=make_user("boss", Level.ADMIN).username, password="pw12345!")
        self.template = ImportTemplate.objects.get(name="電商後台歷史紀錄")

    def upload(self, template=None, upload=None):
        template = template or self.template
        return self.client.post(reverse("orders_manage:template_test", args=[template.pk]), {"file": upload or xlsx()})


class TemplateEditTests(OrderImportTestCase):
    def test_default_template_maps_history_export(self):
        mappings = {m.field: m.source_column for m in self.template.mappings.all()}
        self.assertEqual(mappings["order_no"], "交易序號")
        self.assertEqual(mappings["quantity"], "小計數量")
        self.assertNotIn("buyer_name", mappings)

    def test_create_saves_only_filled_mappings(self):
        response = self.client.post(reverse("orders_manage:template_create"), form_data(src_quantity=" 數量 ", req_quantity="on"))
        self.assertRedirects(response, reverse("orders_manage:template_list"))
        template = ImportTemplate.objects.get(name="測試範本")
        self.assertEqual(
            {(m.field, m.source_column, m.required) for m in template.mappings.all()},
            {("order_no", "交易序號", False), ("quantity", "數量", True)},
        )

    def test_rename_source_column_and_clear_mapping(self):
        data = {"name": self.template.name, "header_row": 1, "note": "", "src_order_no": "訂單編號", "src_quantity": "小計數量"}
        self.client.post(reverse("orders_manage:template_edit", args=[self.template.pk]), data)
        mappings = {m.field: m.source_column for m in self.template.mappings.all()}
        self.assertEqual(mappings, {"order_no": "訂單編號", "quantity": "小計數量"})

    def test_order_no_always_required_and_required_needs_source(self):
        response = self.client.post(reverse("orders_manage:template_create"), form_data(src_order_no="", req_quantity="on"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("src_order_no", response.context["form"].errors)
        self.assertIn("src_quantity", response.context["form"].errors)
        self.assertFalse(ImportTemplate.objects.filter(name="測試範本").exists())

    def test_delete_template_removes_mappings(self):
        self.client.post(reverse("orders_manage:template_delete", args=[self.template.pk]))
        self.assertFalse(FieldMapping.objects.exists())

    def test_page_permission(self):
        self.client.login(username=make_user("lead", Level.LEADER).username, password="pw12345!")
        url = reverse("orders_manage:template_list")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse("orders_manage:template_test", args=[self.template.pk])).status_code, 403)
        PagePermission.objects.create(page_key="manage-order-import", label="匯入欄位對應", min_level=Level.LEADER)
        self.assertEqual(self.client.get(url).status_code, 200)


class TestFileTests(OrderImportTestCase):
    def test_default_template_reads_export(self):
        result = self.upload().context["result"]
        self.assertTrue(result.ok)
        self.assertEqual(result.checked_rows, 3)
        labels = [c.field.label for c in result.mapped_checks]
        self.assertEqual(labels, ["訂單號", "平台", "下單時間", "出貨時間", "商品編號", "數量"])
        first = [value for value, _ in result.preview[0]]
        self.assertEqual(first[0], "13132187")  # 數字欄轉成文字，不會變成 13132187.0
        self.assertEqual(first[3].strftime("%Y-%m-%d %H:%M"), "2026-08-10 11:06")
        self.assertEqual(first[5], 12)
        # 有設定、檔案裡沒有的欄位只是警告；檔案裡沒用到的欄位會列出來
        self.assertIn("店鋪", [c.field.label for c in result.missing_optional])
        self.assertIn("買家姓名", result.unmapped_columns)
        self.template.refresh_from_db()
        self.assertEqual(self.template.known_columns, HEADERS)

    def test_renamed_column_fails_until_mapping_updated(self):
        renamed = ["訂單編號" if h == "交易序號" else h for h in HEADERS]
        response = self.upload(upload=xlsx(renamed))
        self.assertContains(response, "檔案裡沒有「交易序號」這一欄")
        self.assertFalse(response.context["result"].ok)

        FieldMapping.objects.filter(template=self.template, field="order_no").update(source_column="訂單編號")
        self.assertTrue(self.upload(upload=xlsx(renamed)).context["result"].ok)

    def test_conversion_errors_and_blank_required(self):
        rows = [["蝦皮購物", 1, "", "下週", "A", "兩個", ""], ["蝦皮購物", "", "", "2026-08-10", "B", 1, ""]]
        result = self.upload(upload=xlsx(rows=rows)).context["result"]
        self.assertFalse(result.ok)
        self.assertEqual(dict(result.error_summary), {"出貨時間": 1, "數量": 1, "訂單號": 1})
        self.assertIn((3, "訂單號", "", "必填卻是空白"), result.error_samples)

    def test_header_row_setting(self):
        self.template.header_row = 3
        self.template.save()
        self.assertTrue(self.upload(upload=xlsx(title_rows=2)).context["result"].ok)

    def test_csv_big5(self):
        text = "交易序號,小計數量,出貨日期\r\n13132187,2,2026/08/10\r\n"
        result = self.upload(upload=SimpleUploadedFile("a.csv", text.encode("cp950"))).context["result"]
        self.assertTrue(result.ok)
        self.assertEqual([v for v, _ in result.preview[0]][0], "13132187")

    def test_unsupported_file(self):
        response = self.upload(upload=SimpleUploadedFile("a.xls", b"xx"))
        self.assertContains(response, "只支援 .xlsx 或 .csv 檔")
        self.assertNotIn("result", response.context)
