from datetime import datetime
from io import BytesIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from apps.accounts.models import PagePermission
from apps.accounts.testing import Level, make_user

from .models import ColumnMapping, ImportBatch, MappingVersion, OrderLine

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


STAT_HEADERS = ["交易平台", "交易序號", "出貨類型", "商品編號", "建立時間"]
STAT_ROWS = [
    ["蝦皮購物", 1, "蝦皮無包裝", "A", "2026/08/07 15:00:00"],
    ["蝦皮購物", 1, "蝦皮無包裝", "B", "2026/08/07 15:00:00"],
    ["蝦皮購物", 2, "蝦皮無包裝", "A", "2026/08/07 09:00:00"],
    ["蝦皮購物", 3, "蝦皮無包裝[代收]", "A", ""],
    ["蝦皮購物", 4, "蝦皮店到店", "A", ""],
    ["蝦皮購物", 4, "蝦皮店到店", "B", ""],
    ["friDay商城", 5, "7-11", "A", "2026/08/07 14:00:59"],
    ["friDay商城", 5, "7-11", "B", "2026/08/07 14:00:59"],
    ["friDay商城", 6, "7-11", "A", "2026/08/07 14:01:00"],
]


class ImportStatsTests(TestCase):
    def setUp(self):
        self.user = make_user("boss", Level.ADMIN)
        self.client.login(username=self.user.username, password="pw12345!")

    def upload(self, rows=STAT_ROWS, headers=STAT_HEADERS, name="今天.xlsx"):
        return self.client.post(reverse("orders:batch_list"), {"file": xlsx(headers, rows, name=name)})

    def stats(self, batch):
        response = self.client.get(reverse("orders:batch_detail", args=[batch.pk]))
        return {(r.platform, r.ship_type, r.period): (r.distinct, r.rows if r.show_rows else None) for r in response.context["rows"]}

    def test_import_creates_batch_and_stats(self):
        response = self.upload()
        batch = ImportBatch.objects.get()
        self.assertRedirects(response, reverse("orders:batch_detail", args=[batch.pk]))
        self.assertEqual((batch.file_name, batch.imported_by, batch.mapping_version.number), ("今天.xlsx", self.user, 1))
        self.assertEqual((batch.line_count, batch.order_count), (9, 6))
        self.assertEqual(self.stats(batch), {
            ("蝦皮購物", "蝦皮無包裝", ""): (2, 3),  # 去重 2 張、非去重 3 列；蝦皮不分 14:00 前後
            ("蝦皮購物", "蝦皮無包裝[代收]", ""): (1, 1),
            ("蝦皮購物", "蝦皮店到店", ""): (1, None),  # 其他出貨方式只有去重
            ("friDay商城", "7-11", "14:00 前"): (1, None),  # 14:00:59 只看到分鐘，算 14:00 前
            ("friDay商城", "7-11", "14:00 後"): (1, None),
        })

    def test_each_batch_counted_alone(self):
        self.upload()
        self.upload(STAT_ROWS[:2], name="補單.xlsx")
        second = ImportBatch.objects.get(file_name="補單.xlsx")
        self.assertEqual(self.stats(second), {("蝦皮購物", "蝦皮無包裝", ""): (1, 2)})
        self.assertEqual(ImportBatch.objects.get(file_name="今天.xlsx").order_count, 6)

    def test_any_error_rejects_whole_file(self):
        rows = STAT_ROWS + [["蝦皮購物", "", "蝦皮店到店", "A", ""], ["friDay商城", 7, "7-11", "A", ""], ["蝦皮購物", 8, "蝦皮店到店", "A", "明天"]]
        response = self.upload(rows)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "有 3 列資料有問題，整份沒有匯入")
        errors = response.context["outcome"].errors
        self.assertEqual([(row_no, label) for row_no, label, _, _ in errors], [(11, "訂單號"), (12, "下單時間"), (13, "下單時間")])
        self.assertFalse(ImportBatch.objects.exists())
        self.assertFalse(OrderLine.objects.exists())

    def test_missing_order_no_column(self):
        response = self.upload(headers=["交易平台", "訂單編號", "出貨類型", "商品編號", "建立時間"])
        self.assertContains(response, "找不到 訂單號（「交易序號」）")
        self.assertFalse(ImportBatch.objects.exists())

    def test_delete_batch(self):
        self.upload()
        batch = ImportBatch.objects.get()
        self.client.post(reverse("orders:batch_delete", args=[batch.pk]))
        self.assertFalse(ImportBatch.objects.exists())
        self.assertFalse(OrderLine.objects.exists())

    def test_page_permission(self):
        self.client.login(username=make_user("staff", Level.STAFF).username, password="pw12345!")
        self.assertEqual(self.client.get(reverse("orders:batch_list")).status_code, 403)
        self.assertEqual(self.upload().status_code, 403)
        PagePermission.objects.create(page_key="order-stats", label="訂單統計", min_level=Level.STAFF)
        self.assertContains(self.client.get(reverse("orders:batch_list")), "還沒有匯入過")

    def test_date_only_order_time_uses_import_time(self):
        rows = [["friDay商城", 9, "7-11", "A", "2026/08/07 00:00:00"], ["friDay商城", 10, "7-11", "A", "2026/08/07"], ["friDay商城", 11, "7-11", "A", "2026/08/07 16:30:00"]]
        for clock, expected in [("13:00", "14:00 前"), ("14:00", "14:00 前"), ("15:00", "14:00 後")]:
            hour, minute = map(int, clock.split(":"))
            now = timezone.make_aware(datetime(2026, 10, 26, hour, minute, 30))
            with mock.patch("django.utils.timezone.now", return_value=now):
                self.upload(rows, name=f"{clock}.xlsx")
            batch = ImportBatch.objects.get(file_name=f"{clock}.xlsx")
            stats = self.stats(batch)
            # 00:00:00 的兩張依匯入時間；有實際時間的照下單時間（16:30 → 14:00 後）
            if expected == "14:00 前":
                self.assertEqual(stats, {("friDay商城", "7-11", "14:00 前"): (2, None), ("friDay商城", "7-11", "14:00 後"): (1, None)})
            else:
                self.assertEqual(stats, {("friDay商城", "7-11", "14:00 後"): (3, None)})
            response = self.client.get(reverse("orders:batch_detail", args=[batch.pk]))
            self.assertContains(response, f"有 2 張訂單的下單時間是 00:00:00，依匯入時間 {clock} 算在\n      {expected}")
