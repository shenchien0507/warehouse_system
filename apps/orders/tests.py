import re
import zipfile
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

from .models import ColumnMapping, GroupVersion, ImportBatch, MappingVersion, OrderLine, StatGroup

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


def xlsx_wrong_dimension(**kwargs):
    """模擬有些系統匯出的檔案：工作表記錄的範圍只寫 A1:A1。"""
    upload = xlsx(**kwargs)
    source, target = zipfile.ZipFile(BytesIO(upload.read())), BytesIO()
    with zipfile.ZipFile(target, "w") as out:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(rb'<dimension ref="[^"]*"', b'<dimension ref="A1:A1"', data)
            out.writestr(item, data)
    return SimpleUploadedFile(upload.name, target.getvalue())


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

    def test_file_with_wrong_dimension_reads_all_columns(self):
        version = self.create_version(xlsx_wrong_dimension())
        self.assertEqual(version.source_columns, HEADERS)

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
    ["蝦皮購物", 3, "蝦皮無包裝[代收]", "A", "2026/08/07 10:00:00"],
    ["蝦皮購物", 12, "蝦皮隔日到貨", "A", "2026/08/07 20:00:00"],
    ["蝦皮購物", 4, "蝦皮店到店", "A", ""],
    ["蝦皮購物", 4, "蝦皮店到店", "B", ""],
    ["friDay商城", 5, "7-11", "A", "2026/08/07 14:00:59"],
    ["friDay商城", 5, "7-11", "B", "2026/08/07 14:00:59"],
    ["friDay商城", 6, "7-11", "A", "2026/08/07 14:01:00"],
]


class ImportStatsTests(TestCase):
    """預設分組重現原本的規則：蝦皮無包裝、蝦皮隔日到貨分 14:00 前後，蝦皮其他不分，其他平台分 14:00 前後且 00:00:00 用匯入時間。"""

    def setUp(self):
        self.user = make_user("boss", Level.ADMIN)
        self.client.login(username=self.user.username, password="pw12345!")

    def upload(self, rows=STAT_ROWS, headers=STAT_HEADERS, name="今天.xlsx"):
        return self.client.post(reverse("orders:batch_list"), {"file": xlsx(headers, rows, name=name)})

    def response(self, batch):
        return self.client.get(reverse("orders:batch_detail", args=[batch.pk]))

    def stats(self, batch, keep_zero=False):
        rows = self.response(batch).context["summary"].groups
        return {
            (r.name, r.period): (r.count.distinct, r.count.rows if r.show_rows else None)
            for r in rows if keep_zero or r.count.rows
        }

    def test_import_creates_batch_and_stats(self):
        response = self.upload()
        batch = ImportBatch.objects.get()
        self.assertRedirects(response, reverse("orders:batch_detail", args=[batch.pk]))
        self.assertEqual((batch.file_name, batch.imported_by, batch.mapping_version.number), ("今天.xlsx", self.user, 1))
        self.assertEqual((batch.line_count, batch.order_count), (10, 7))
        self.assertEqual(self.stats(batch, keep_zero=True), {
            # 蝦皮無包裝（含[代收]）：去重和非去重，分 14:00 前後
            ("蝦皮無包裝", "14:00 前"): (2, 2),
            ("蝦皮無包裝", "14:00 後"): (1, 2),
            ("蝦皮隔日到貨", "14:00 後"): (1, None),
            ("蝦皮其他", ""): (1, None),
            ("其他平台", "14:00 前"): (1, None),  # 14:00:59 只看到分鐘，算 14:00 前
            ("其他平台", "14:00 後"): (1, None),
        })
        details = {(r.group, r.ship_type, r.period): r.count.distinct for r in self.response(batch).context["summary"].details}
        self.assertEqual(details[("蝦皮無包裝", "蝦皮無包裝[代收]", "14:00 前")], 1)

    def test_each_batch_counted_alone(self):
        self.upload()
        self.upload(STAT_ROWS[:2], name="補單.xlsx")
        second = ImportBatch.objects.get(file_name="補單.xlsx")
        self.assertEqual(self.stats(second), {("蝦皮無包裝", "14:00 後"): (1, 2)})
        self.assertEqual(ImportBatch.objects.get(file_name="今天.xlsx").order_count, 7)

    def test_any_error_rejects_whole_file(self):
        rows = STAT_ROWS + [["蝦皮購物", "", "蝦皮店到店", "A", ""], ["蝦皮購物", 8, "蝦皮店到店", "A", "明天"]]
        response = self.upload(rows)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "有 2 列資料有問題，整份沒有匯入")
        errors = response.context["outcome"].errors
        self.assertEqual([(row_no, label) for row_no, label, _, _ in errors], [(12, "訂單號"), (13, "下單時間")])
        self.assertFalse(ImportBatch.objects.exists())
        self.assertFalse(OrderLine.objects.exists())

    def test_blank_order_time_listed_separately(self):
        self.upload([["friDay商城", 7, "7-11", "A", ""]])
        self.assertEqual(self.stats(ImportBatch.objects.get()), {("其他平台", "沒有下單時間"): (1, None)})

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

    def upload_at(self, clock, rows):
        hour, minute = map(int, clock.split(":"))
        now = timezone.make_aware(datetime(2026, 10, 26, hour, minute, 30))
        with mock.patch("django.utils.timezone.now", return_value=now):
            self.upload(rows, name=f"{clock}.xlsx")
        return ImportBatch.objects.get(file_name=f"{clock}.xlsx")

    def test_date_only_order_time_uses_import_time(self):
        rows = [["friDay商城", 9, "7-11", "A", "2026/08/07 00:00:00"], ["friDay商城", 10, "7-11", "A", "2026/08/07"], ["friDay商城", 11, "7-11", "A", "2026/08/07 16:30:00"]]
        for clock, expected in [("13:00", {"14:00 前": 2, "14:00 後": 1}), ("14:00", {"14:00 前": 2, "14:00 後": 1}), ("15:00", {"14:00 後": 3})]:
            batch = self.upload_at(clock, rows)
            # 00:00:00 的兩張依匯入時間；有實際時間的照下單時間（16:30 → 14:00 後）
            self.assertEqual(self.stats(batch), {("其他平台", p): (n, None) for p, n in expected.items()})
            self.assertContains(self.response(batch), f"有 2 張訂單的下單時間是 00:00:00，依匯入時間 {clock} 判斷前後")

    def test_midnight_rule_is_per_group(self):
        group = StatGroup.objects.get(name="其他平台")  # v1 已鎖定，這裡直接改資料模擬「沒勾選」的分組
        group.midnight_uses_import_time = False
        group.save()
        batch = self.upload_at("15:00", [["friDay商城", 9, "7-11", "A", "2026/08/07 00:00:00"]])
        self.assertEqual(self.stats(batch), {("其他平台", "14:00 前"): (1, None)})  # 沒勾：00:00 照資料算


SOURCE_HEADERS = ["交易平台", "交易店鋪", "交易序號", "出貨類型"]
SOURCE_ROWS = [
    ["蝦皮購物", "蝦皮購物_0號店", 1, "蝦皮無包裝"],
    ["蝦皮購物", "蝦皮購物_0號店", 1, "蝦皮無包裝"],
    ["蝦皮購物", "蝦皮購物_1號店", 2, "蝦皮店到店"],
    ["MOMO", "MOMO_1號店", 3, "宅配"],
    ["friDay商城", "friDay商城_0號店", 4, "7-11"],
    ["蝦皮購物", "", 5, "蝦皮隔日到貨"],
]


class StatGroupTests(TestCase):
    def setUp(self):
        self.client.login(username=make_user("boss", Level.ADMIN).username, password="pw12345!")
        self.client.post(reverse("orders:batch_list"), {"file": xlsx(STAT_HEADERS, STAT_ROWS, name="v1.xlsx")})
        self.v1 = GroupVersion.objects.get(number=1)

    def new_version(self, source=True):
        """從 v1 複製成 v2；預設上傳來源檔讀出條件選項。"""
        self.client.post(reverse("orders_manage:group_version_copy", args=[self.v1.pk]))
        v2 = GroupVersion.objects.get(number=2)
        if source:
            self.client.post(reverse("orders_manage:group_version_source", args=[v2.pk]), {"file": xlsx(SOURCE_HEADERS, SOURCE_ROWS)})
            v2.refresh_from_db()
        return v2

    def save_group(self, url, conditions, **fields):
        data = {
            "name": "測試", "sort_order": 5, "cutoff": "", "conditions-TOTAL_FORMS": len(conditions),
            "conditions-INITIAL_FORMS": 0, "conditions-MIN_NUM_FORMS": 0, "conditions-MAX_NUM_FORMS": 1000, **fields,
        }
        for i, condition in enumerate(conditions):
            for key, values in condition.items():
                data[f"conditions-{i}-{key}"] = values
        return self.client.post(url, data)

    def stats(self, name="v1.xlsx"):
        batch = ImportBatch.objects.get(file_name=name)
        rows = self.client.get(reverse("orders:batch_detail", args=[batch.pk])).context["summary"].groups
        return {(r.name, r.period): r.count.distinct for r in rows if r.count.rows}

    def test_default_v1_active_and_batch_remembers_it(self):
        self.assertTrue(self.v1.is_active)
        self.assertEqual([g.name for g in self.v1.groups.all()], ["蝦皮無包裝", "蝦皮隔日到貨", "蝦皮其他", "其他平台"])
        self.assertEqual(ImportBatch.objects.get().group_version, self.v1)

    def test_locked_version_cannot_be_edited(self):
        group = self.v1.groups.first()
        response = self.save_group(reverse("orders_manage:group_edit", args=[self.v1.pk, group.pk]), [{"platforms": ["蝦皮購物"]}], name="改名")
        self.assertRedirects(response, reverse("orders_manage:group_version_detail", args=[self.v1.pk]))
        group.refresh_from_db()
        self.assertEqual(group.name, "蝦皮無包裝")
        self.client.post(reverse("orders_manage:group_delete", args=[self.v1.pk, group.pk]))
        self.assertTrue(StatGroup.objects.filter(pk=group.pk).exists())
        self.assertEqual(self.client.post(reverse("orders_manage:group_version_delete", args=[self.v1.pk])).status_code, 404)

    def test_new_version_with_own_cutoff_only_affects_later_batches(self):
        v2 = self.new_version()
        self.assertEqual(v2.status, "草稿")
        self.assertEqual(v2.groups.count(), 4)
        response = self.save_group(
            reverse("orders_manage:group_create", args=[v2.pk]), [{"platforms": ["friDay商城"]}, {"ship_types": ["蝦皮隔日到貨"]}],
            name="中午切", cutoff="1430",
        )
        self.assertRedirects(response, reverse("orders_manage:group_version_detail", args=[v2.pk]))
        group = v2.groups.get(name="中午切")
        self.assertEqual(group.cutoff.strftime("%H:%M"), "14:30")
        self.assertEqual([c.describe() for c in group.conditions.all()], ["平台：friDay商城", "出貨類型：蝦皮隔日到貨"])

        # 草稿還沒生效：新匯入仍用 v1
        self.client.post(reverse("orders:batch_list"), {"file": xlsx(STAT_HEADERS, STAT_ROWS, name="草稿時.xlsx")})
        self.assertEqual(ImportBatch.objects.get(file_name="草稿時.xlsx").group_version, self.v1)

        self.client.post(reverse("orders_manage:group_version_activate", args=[v2.pk]))
        v2.refresh_from_db()
        self.v1.refresh_from_db()
        self.assertTrue(v2.is_active)
        self.assertFalse(self.v1.is_active)
        self.client.post(reverse("orders:batch_list"), {"file": xlsx(STAT_HEADERS, STAT_ROWS, name="v2.xlsx")})
        # v2：順序 5 排最前面，friDay 和隔日到貨都算進「中午切」，依 14:30 切開
        self.assertEqual(self.stats("v2.xlsx")[("中午切", "14:30 前")], 2)  # friDay 5（14:00）、6（14:01）
        self.assertEqual(self.stats("v2.xlsx")[("中午切", "14:30 後")], 1)  # 隔日到貨 12（20:00）
        # 舊批次照 v1，數字不變
        self.assertEqual(self.stats("v1.xlsx")[("其他平台", "14:00 前")], 1)
        self.assertNotIn(("中午切", "14:30 前"), self.stats("v1.xlsx"))

    def test_condition_required(self):
        v2 = self.new_version()
        response = self.save_group(reverse("orders_manage:group_create", args=[v2.pk]), [{}])
        self.assertContains(response, "至少要選一組條件")
        self.assertFalse(StatGroup.objects.filter(name="測試").exists())

    def test_ungrouped(self):
        v2 = self.new_version()
        other = v2.groups.get(name="其他平台")
        self.client.post(reverse("orders_manage:group_delete", args=[v2.pk, other.pk]))
        self.client.post(reverse("orders_manage:group_version_activate", args=[v2.pk]))
        self.client.post(reverse("orders:batch_list"), {"file": xlsx(STAT_HEADERS, STAT_ROWS, name="v2.xlsx")})
        self.assertEqual(self.stats("v2.xlsx")[("未分組", "")], 2)

    def test_create_blank_version_reads_source_file(self):
        self.assertContains(self.client.get(reverse("orders_manage:group_version_list")), reverse("orders_manage:group_version_create"))
        response = self.client.post(reverse("orders_manage:group_version_create"), {"note": "從頭來", "file": xlsx(SOURCE_HEADERS, SOURCE_ROWS)})
        v2 = GroupVersion.objects.get(number=2)
        self.assertRedirects(response, reverse("orders_manage:group_version_detail", args=[v2.pk]))
        self.assertEqual((v2.status, v2.note, v2.groups.count(), v2.source_file_name), ("草稿", "從頭來", 0, "匯出.xlsx"))
        self.assertEqual(v2.source_combos, [
            ["MOMO", "MOMO_1號店", "宅配"],
            ["friDay商城", "friDay商城_0號店", "7-11"],
            ["蝦皮購物", "", "蝦皮隔日到貨"],
            ["蝦皮購物", "蝦皮購物_0號店", "蝦皮無包裝"],
            ["蝦皮購物", "蝦皮購物_1號店", "蝦皮店到店"],
        ])
        self.assertContains(self.client.get(reverse("orders_manage:group_version_detail", args=[v2.pk])), "讀到 3 個平台、5 種")
        self.save_group(reverse("orders_manage:group_create", args=[v2.pk]), [{}], name="全部", cutoff="1200")
        self.save_group(reverse("orders_manage:group_create", args=[v2.pk]), [{"platforms": ["MOMO"]}], name="全部")
        self.assertEqual(v2.groups.count(), 1)  # 沒有條件不能存；第二次可以

    def test_create_version_needs_readable_file(self):
        response = self.client.post(reverse("orders_manage:group_version_create"), {"file": xlsx(["欄A"], [[1]])})
        self.assertContains(response, "找不到平台、店鋪、出貨方式任何一欄")
        self.assertFalse(GroupVersion.objects.filter(number=2).exists())

    def test_options_only_from_source_file(self):
        v2 = self.new_version()
        response = self.client.get(reverse("orders_manage:group_create", args=[v2.pk]))
        self.assertContains(response, 'value="MOMO_1號店"')
        self.assertNotContains(response, 'value="蝦皮無包裝[代收]"')  # 匯入過的資料有，但來源檔沒有
        self.assertEqual(response.context["combos"], v2.source_combos)  # 連動用的組合
        self.assertContains(response, 'id="source-combos"')
        response = self.save_group(reverse("orders_manage:group_create", args=[v2.pk]), [{"platforms": ["不存在"]}], name="X")
        self.assertIn("platforms", response.context["formset"].forms[0].errors)

    def test_version_without_source_asks_for_upload(self):
        v2 = self.new_version(source=False)
        self.assertContains(self.client.get(reverse("orders_manage:group_version_detail", args=[v2.pk])), "還沒有來源檔")
        response = self.client.get(reverse("orders_manage:group_create", args=[v2.pk]))
        self.assertRedirects(response, reverse("orders_manage:group_version_detail", args=[v2.pk]))

    def test_saved_conditions_are_locked_in_form(self):
        v2 = self.new_version()
        group = v2.groups.get(name="其他平台")
        group.conditions.update(platforms=["MOMO"])
        response = self.client.get(reverse("orders_manage:group_edit", args=[v2.pk, group.pk]))
        self.assertContains(response, "平台：MOMO")
        self.assertContains(response, "修改這組條件")
        self.assertContains(response, '<div class="row g-3" data-options hidden>', html=False)  # 已存的條件
        self.assertEqual(len(response.context["formset"].forms), 1)  # 編輯時不自動多一組空白條件
        response = self.client.get(reverse("orders_manage:group_create", args=[v2.pk]))
        self.assertEqual(len(response.context["formset"].forms), 1)  # 新增分組先給一組空白條件
        self.assertContains(response, '<div class="row g-3" data-options>', html=False)  # 空白的條件可直接勾

    def test_cannot_change_source_of_locked_version(self):
        self.client.post(reverse("orders_manage:group_version_source", args=[self.v1.pk]), {"file": xlsx(SOURCE_HEADERS, SOURCE_ROWS)})
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.source_combos, [])

    def test_copy_keeps_source(self):
        v2 = self.new_version()
        self.client.post(reverse("orders_manage:group_version_copy", args=[v2.pk]))
        self.assertEqual(GroupVersion.objects.get(number=3).source_combos, v2.source_combos)

    def test_cannot_activate_empty_version(self):
        v2 = self.new_version()
        v2.groups.all().delete()
        self.client.post(reverse("orders_manage:group_version_activate", args=[v2.pk]))
        v2.refresh_from_db()
        self.assertFalse(v2.is_active)

    def test_pages_render(self):
        v2 = self.new_version()
        self.assertContains(self.client.get(reverse("orders_manage:group_version_list")), "生效中")
        response = self.client.get(reverse("orders_manage:group_version_detail", args=[self.v1.pk]))
        self.assertContains(response, "14:00（00:00:00 用匯入時間）")
        self.assertNotContains(response, "新增分組")
        self.assertContains(self.client.get(reverse("orders_manage:group_version_detail", args=[v2.pk])), "新增分組")
        group = v2.groups.first()
        self.assertContains(self.client.get(reverse("orders_manage:group_edit", args=[v2.pk, group.pk])), 'value="14:00"')

    def test_menu_permission(self):
        self.client.login(username=make_user("lead", Level.LEADER).username, password="pw12345!")
        self.assertEqual(self.client.get(reverse("orders_manage:group_version_list")).status_code, 403)
        self.assertEqual(self.client.post(reverse("orders_manage:group_version_copy", args=[self.v1.pk])).status_code, 403)
