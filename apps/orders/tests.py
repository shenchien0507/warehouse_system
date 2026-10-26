from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from apps.accounts.models import PagePermission
from apps.accounts.testing import Level, make_user

from .models import ColumnMapping, MappingVersion

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


class MappingTestCase(TestCase):
    def setUp(self):
        self.client.login(username=make_user("boss", Level.ADMIN).username, password="pw12345!")
        self.v1 = MappingVersion.objects.get(number=1)

    def create_version(self, upload=None, header_row=1):
        self.client.post(reverse("orders_manage:version_create"), {"file": upload or xlsx(), "header_row": header_row})
        return MappingVersion.objects.order_by("-number").first()

    def save_mapping(self, version, **mapping):
        return self.client.post(reverse("orders_manage:version_detail", args=[version.pk]), {"note": "", **mapping})

    def check(self, version, upload=None):
        return self.client.post(reverse("orders_manage:version_check", args=[version.pk]), {"file": upload or xlsx()})


class VersionTests(MappingTestCase):
    def test_default_v1_is_active_and_maps_12_fields(self):
        self.assertTrue(self.v1.is_active)
        self.assertTrue(self.v1.is_locked)
        mapping = self.v1.mapping_dict()
        self.assertEqual(len(mapping), 12)
        self.assertEqual(mapping["order_no"], "交易序號")
        self.assertNotIn("配送狀態", mapping.values())

    def test_upload_creates_draft_with_file_columns_and_carries_matching_mappings(self):
        version = self.create_version()
        self.assertEqual(version.number, 2)
        self.assertEqual(version.status, "草稿")
        self.assertEqual(version.source_columns, HEADERS)
        self.assertEqual(version.source_file_name, "匯出.xlsx")
        # v1 的對應裡，新檔也有的欄名才帶入
        self.assertEqual(
            version.mapping_dict(),
            {"order_no": "交易序號", "platform": "交易平台", "order_time": "建立時間", "ship_time": "出貨日期", "product_code": "商品編號", "quantity": "小計數量"},
        )
        response = self.client.get(reverse("orders_manage:version_detail", args=[version.pk]))
        self.assertContains(response, '<option value="買家姓名">買家姓名</option>', html=True)

    def test_header_row(self):
        version = self.create_version(xlsx(title_rows=2), header_row=3)
        self.assertEqual(version.source_columns, HEADERS)

    def test_one_source_column_per_field(self):
        version = self.create_version()
        response = self.save_mapping(version, order_no="交易序號", ship_time="出貨日期", quantity="交易序號")
        self.assertEqual(response.status_code, 200)
        self.assertIn("quantity", response.context["form"].errors)
        self.assertEqual(version.mapping_dict()["quantity"], "小計數量")  # 沒存

    def test_choice_must_come_from_file_and_order_no_must_be_mapped(self):
        version = self.create_version()
        response = self.save_mapping(version, order_no="不存在的欄", quantity="小計數量")
        self.assertIn("order_no", response.context["form"].errors)
        response = self.save_mapping(version, order_no="")
        self.assertIn("order_no", response.context["form"].errors)
        self.assertRedirects(self.save_mapping(version, order_no="交易序號"), reverse("orders_manage:version_detail", args=[version.pk]))
        self.assertEqual(version.mapping_dict(), {"order_no": "交易序號"})

    def test_save_draft_then_activate_switches_active_version(self):
        version = self.create_version()
        response = self.save_mapping(version, order_no="交易序號", ship_time="建立時間", quantity="小計數量", product_code="商品編號")
        self.assertRedirects(response, reverse("orders_manage:version_detail", args=[version.pk]))
        self.assertEqual(version.mapping_dict(), {"order_no": "交易序號", "ship_time": "建立時間", "quantity": "小計數量", "product_code": "商品編號"})

        self.client.post(reverse("orders_manage:version_activate", args=[version.pk]))
        version.refresh_from_db()
        self.v1.refresh_from_db()
        self.assertTrue(version.is_active)
        self.assertFalse(self.v1.is_active)
        self.assertEqual(MappingVersion.objects.filter(is_active=True).count(), 1)
        self.assertEqual(self.v1.status, "已停用")

        # 切回舊版本
        self.client.post(reverse("orders_manage:version_activate", args=[self.v1.pk]))
        self.assertEqual(MappingVersion.active(), self.v1)

    def test_cannot_activate_without_order_no(self):
        version = self.create_version(xlsx(headers=["訂單編號", "小計數量"], rows=[[1, 1]]))
        self.assertEqual([f.key for f in version.missing_must_map()], ["order_no"])
        self.client.post(reverse("orders_manage:version_activate", args=[version.pk]))
        version.refresh_from_db()
        self.assertFalse(version.is_active)
        self.assertEqual(MappingVersion.active(), self.v1)

    def test_activated_version_is_locked_copy_to_change(self):
        response = self.save_mapping(self.v1, order_no="平台訂單編號", ship_time="出貨日期", quantity="小計數量")
        self.assertRedirects(response, reverse("orders_manage:version_detail", args=[self.v1.pk]))
        self.assertEqual(self.v1.mapping_dict()["order_no"], "交易序號")
        self.assertEqual(self.client.post(reverse("orders_manage:version_delete", args=[self.v1.pk])).status_code, 404)

        self.client.post(reverse("orders_manage:version_copy", args=[self.v1.pk]))
        copy = MappingVersion.objects.get(number=2)
        self.assertEqual(copy.status, "草稿")
        self.assertEqual(copy.mapping_dict(), self.v1.mapping_dict())
        self.assertEqual(copy.source_columns, self.v1.source_columns)

    def test_delete_draft(self):
        version = self.create_version()
        self.client.post(reverse("orders_manage:version_delete", args=[version.pk]))
        self.assertFalse(MappingVersion.objects.filter(pk=version.pk).exists())
        self.assertFalse(ColumnMapping.objects.filter(version_id=version.pk).exists())

    def test_upload_errors(self):
        response = self.client.post(reverse("orders_manage:version_create"), {"file": SimpleUploadedFile("a.xls", b"xx"), "header_row": 1})
        self.assertContains(response, "只支援 .xlsx 或 .csv 檔")
        response = self.client.post(reverse("orders_manage:version_create"), {"file": xlsx(), "header_row": 9})
        self.assertContains(response, "沒有資料")
        self.assertEqual(MappingVersion.objects.count(), 1)

    def test_page_permission(self):
        self.client.login(username=make_user("lead", Level.LEADER).username, password="pw12345!")
        url = reverse("orders_manage:version_list")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(reverse("orders_manage:version_activate", args=[self.v1.pk])).status_code, 403)
        PagePermission.objects.create(page_key="manage-order-import", label="匯入欄位對應", min_level=Level.LEADER)
        self.assertContains(self.client.get(url), "生效中")


class CheckFileTests(MappingTestCase):
    def test_v1_reads_export(self):
        response = self.check(self.v1)
        result = response.context["result"]
        self.assertTrue(result.ok)
        self.assertFalse(response.context["form"].errors)
        self.assertEqual(result.checked_rows, 3)
        labels = [c.field.label for c in result.mapped_checks]
        self.assertEqual(labels, ["訂單號", "平台", "下單時間", "出貨時間", "商品編號", "數量"])
        first = [value for value, _ in result.preview[0]]
        self.assertEqual(first[0], "13132187")  # 數字欄轉成文字，不會變成 13132187.0
        self.assertEqual(first[3].strftime("%Y-%m-%d %H:%M"), "2026-08-10 11:06")
        self.assertEqual(first[5], 12)
        self.assertIn("店鋪", [c.field.label for c in result.missing_optional])
        self.assertIn("買家姓名", result.unmapped_columns)

    def test_renamed_column_fails(self):
        renamed = ["訂單編號" if h == "交易序號" else h for h in HEADERS]
        response = self.check(self.v1, xlsx(renamed))
        self.assertContains(response, "檔案裡沒有「交易序號」這一欄")
        self.assertFalse(response.context["result"].ok)

    def test_conversion_errors_and_blanks_only_counted(self):
        rows = [["蝦皮購物", 1, "", "下週", "A", "兩個", ""], ["蝦皮購物", "", "", "2026-08-10", "B", 1, ""]]
        result = self.check(self.v1, xlsx(rows=rows)).context["result"]
        self.assertFalse(result.ok)
        self.assertEqual(dict(result.error_summary), {"出貨時間": 1, "數量": 1})
        self.assertIn((2, "數量", "兩個", "不是整數"), result.error_samples)
        # 空白不算錯誤，只列出格數
        self.assertEqual(dict(result.blank_summary), {"訂單號": 1, "下單時間": 2})

    def test_blanks_alone_are_ok(self):
        rows = [["蝦皮購物", 1, "", "", "A", "", ""]]
        result = self.check(self.v1, xlsx(rows=rows)).context["result"]
        self.assertTrue(result.ok)
        self.assertEqual(dict(result.blank_summary), {"下單時間": 1, "出貨時間": 1, "數量": 1})

    def test_csv_big5(self):
        text = "交易序號,小計數量,出貨日期\r\n13132187,2,2026/08/10\r\n"
        result = self.check(self.v1, SimpleUploadedFile("a.csv", text.encode("cp950"))).context["result"]
        self.assertTrue(result.ok)
        self.assertEqual([v for v, _ in result.preview[0]][0], "13132187")
