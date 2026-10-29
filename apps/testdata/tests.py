import tempfile
import zipfile
from collections import defaultdict
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.testing import Level, make_user
from apps.orders.importer import read_rows

from . import simulation
from .generator import COLUMNS, MASK

CATALOG = {
    "platforms": [
        {"name": "蝦皮購物", "share": 90, "shops": ["蝦皮購物_0號店", "蝦皮購物_1號店"],
         "ship_types": [["蝦皮無包裝", 60], ["蝦皮店到店", 30]], "date_only": False, "order_no_shapes": ["######NAN#D#W#"]},
        {"name": "friDay商城", "share": 10, "shops": ["friDay商城_3號店"],
         "ship_types": [["7-11", 10]], "date_only": True, "order_no_shapes": ["##############"]},
    ],
    "shipment_shapes": {"蝦皮無包裝": ["TW############U"]},
    "products": [["DO528", "手提雙飲保溫杯", "天空藍-F", 187], ["DO601", "TF高速記憶卡", "128G-F", 793],
                 ["DO479", "防誤食安全餌劑盒", "單入-F", 370]],
}


def form_data(**overrides):
    data = {"first_order_no": 1000}
    for key in ("urgent", "shipping", "new", "formal"):
        data.update({f"{key}_count": 20, f"{key}_start_date": "2026-10-05", f"{key}_start_time": "08:00",
                     f"{key}_end_date": "2026-10-05", f"{key}_end_time": "14:00"})
    # 比例表：p0 蝦皮購物（店到店）、p1 蝦皮購物（無包裝）、p2 friDay商城
    data.update({"p0": 30, "p0_t0": 100, "p1": 60, "p1_t0": 100, "p2": 10, "p2_t0": 100})
    data.update(overrides)
    return data


@mock.patch("apps.testdata.forms.load_catalog", lambda: CATALOG)
@mock.patch("apps.testdata.generator.load_catalog", lambda: CATALOG)
class GenerateTests(TestCase):
    def setUp(self):
        self.client.login(username=make_user("boss", Level.ADMIN).username, password="pw12345!")

    def post(self, **overrides):
        return self.client.post(reverse("testdata:generate"), form_data(**overrides))

    def files(self, response):
        archive = zipfile.ZipFile(BytesIO(response.content))
        result = {}
        for name in archive.namelist():
            sheet = load_workbook(BytesIO(archive.read(name)), read_only=True).worksheets[0]
            rows = list(sheet.iter_rows(values_only=True))
            result[name.split("_")[0]] = (rows[0], [dict(zip(rows[0], r)) for r in rows[1:]])
        return result

    def test_page_is_admin_only(self):
        self.assertEqual(self.client.get(reverse("testdata:generate")).status_code, 200)
        self.client.login(username=make_user("staff", Level.STAFF).username, password="pw12345!")
        self.assertEqual(self.client.get(reverse("testdata:generate")).status_code, 403)

    def test_generates_one_file_per_type_with_history_columns(self):
        response = self.post()
        self.assertEqual(response["Content-Type"], "application/zip")
        files = self.files(response)
        self.assertEqual(set(files), {"急單", "出貨中", "新訂單", "正式訂單"})
        orders = defaultdict(set)
        for label, (headers, rows) in files.items():
            self.assertEqual(list(headers), COLUMNS)
            for row in rows:
                orders[label].add(row["交易序號"])
                for column in ("買家姓名", "收件者姓名", "收件者手機", "收件者地址"):
                    self.assertEqual(row[column], MASK)
                self.assertIsNone(row["出貨日期"])
                self.assertEqual(bool(row["出貨單號"]), label == "正式訂單")
                if row["交易平台"] == "friDay商城":
                    self.assertEqual(row["建立時間"], "2026/10/05 00:00:00")
                    self.assertEqual(row["出貨類型"], "7-11")
                else:
                    self.assertTrue("2026/10/05 08:00:00" <= row["建立時間"] <= "2026/10/05 14:00:59")
                    self.assertIn(row["出貨類型"], ("蝦皮無包裝", "蝦皮店到店"))
                    self.assertIn(row["交易店鋪"], ("蝦皮購物_0號店", "蝦皮購物_1號店"))
                self.assertEqual(row["商品小計"], row["商品單價"] * row["小計數量"])
        self.assertTrue(all(len(numbers) == 20 for numbers in orders.values()))
        all_numbers = set().union(*orders.values())
        self.assertEqual(all_numbers, set(range(1000, 1080)))  # 4 種類型接續編號、不重複

    def test_zero_ratio_and_zero_count_are_left_out(self):
        files = self.files(self.post(p0=0, p2=0, urgent_count=0, new_count=0))
        self.assertEqual(set(files), {"出貨中", "正式訂單"})
        for _, rows in files.values():
            self.assertTrue(all(r["交易平台"] == "蝦皮購物" and r["出貨類型"] == "蝦皮無包裝" for r in rows))

    def test_no_packaging_ship_types_get_their_own_row(self):
        response = self.client.get(reverse("testdata:generate"))
        rows = [(label, [name for name, _ in types]) for _, label, _, _, types in response.context["form"].platform_rows]
        self.assertEqual(rows, [("蝦皮購物", ["蝦皮店到店"]), ("蝦皮購物（無包裝）", ["蝦皮無包裝"]), ("friDay商城", ["7-11"])])
        form = response.context["form"]
        self.assertEqual([form["p0"].initial, form["p1"].initial, form["p2"].initial], [30.0, 60.0, 10.0])

        files = self.files(self.post(p1=0, p2=0))
        for _, rows in files.values():
            self.assertTrue(all(r["交易平台"] == "蝦皮購物" and r["出貨類型"] == "蝦皮店到店" for r in rows))

    def test_file_reads_with_order_importer(self):
        archive = zipfile.ZipFile(BytesIO(self.post().content))
        upload = BytesIO(archive.read(archive.namelist()[0]))
        upload.name = "急單.xlsx"
        headers, rows = read_rows(upload, 1)
        self.assertEqual(headers, COLUMNS)
        self.assertTrue(list(rows))

    def test_invalid_settings_show_errors(self):
        response = self.post(shipping_end_time="07:00")
        self.assertContains(response, "出貨中：結束時間要晚於開始時間。")
        response = self.post(p0=0, p1=0, p2=0)
        self.assertContains(response, "平台比例至少要有一個大於 0。")
        response = self.post(p1_t0=0)
        self.assertContains(response, "蝦皮購物（無包裝）：平台比例大於 0，出貨類型的比例至少要有一個大於 0。")
        response = self.post(urgent_count=0, shipping_count=0, new_count=0, formal_count=0)
        self.assertContains(response, "至少要有一種類型的訂單數大於 0。")


def order(platform="蝦皮購物", ship_type="蝦皮店到店", created="2026/10/05 10:00:00", status="new", no=1):
    return {"order_no": no, "platform": platform, "ship_type": ship_type, "created": created, "status": status}


class DueDateTests(TestCase):
    def test_same_day_rule_follows_sample_files(self):
        cases = [
            (order(ship_type="蝦皮無包裝[代收]", created="2026/10/05 14:00:59"), date(2026, 10, 5)),
            (order(ship_type="蝦皮無包裝", created="2026/10/05 14:01:00"), date(2026, 10, 6)),
            (order(ship_type="蝦皮隔日到貨", created="2026/10/05 09:00:00"), date(2026, 10, 5)),
            (order(ship_type="蝦皮店到店", created="2026/10/05 09:00:00"), date(2026, 10, 6)),
            (order(platform="自訂交易", ship_type="黑貓", created="2026/10/05 09:00:00"), date(2026, 10, 5)),
            (order(platform="friDay商城", ship_type="7-11", created="2026/10/05 00:00:00"), date(2026, 10, 6)),
        ]
        for o, expected in cases:
            self.assertEqual(simulation.due_date(o), expected, o)


@mock.patch("apps.testdata.forms.load_catalog", lambda: CATALOG)
@mock.patch("apps.testdata.generator.load_catalog", lambda: CATALOG)
@mock.patch("apps.testdata.simulation.load_catalog", lambda: CATALOG)
class SimulationTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(simulation, "STATE_PATH", Path(tmp.name) / "simulation.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.login(username=make_user("boss", Level.ADMIN).username, password="pw12345!")
        self.url = reverse("testdata:simulate")

    def start(self, **overrides):
        data = form_data(action="start", start_date="2026-10-05", start_time="08:00", live="0",
                         orders_per_day=2400, urgent_pct=5, shipping_pct=5, first_order_no=1)
        data.update(overrides)
        return self.client.post(self.url, data)

    def advance(self, **data):
        return self.client.post(self.url, {"action": "advance", **data})

    def pools(self):
        archive = zipfile.ZipFile(BytesIO(self.client.get(reverse("testdata:simulate_pools")).content))
        result = {}
        for name in archive.namelist():
            rows = list(load_workbook(BytesIO(archive.read(name)), read_only=True).worksheets[0].iter_rows(values_only=True))
            result[name.split("_")[0]] = {r[2] for r in rows[1:]}
        return result

    def test_orders_flow_in_and_rounds_take_them_out(self):
        self.assertRedirects(self.start(), self.url)
        self.assertContains(self.client.get(self.url), "2026/10/05 08:00")
        self.assertRedirects(self.advance(minutes=120), self.url)
        state = simulation.load()
        self.assertEqual(state["clock"], "2026/10/05 10:00:00")
        orders = state["orders"]
        self.assertGreater(len(orders), 100)  # 2400 張一天，8～10 點約 180 張
        self.assertTrue(all("2026/10/05 08:00:00" <= o["created"] < "2026/10/05 10:00:00" or o["created"].endswith("00:00:00")
                            for o in orders))

        pools = self.pools()
        self.assertEqual(set(pools), {"新訂單", "急單", "出貨中"})
        self.assertEqual(sum(len(v) for v in pools.values()), len(orders))
        urgent, shipping = len(pools["急單"]), len(pools["出貨中"])
        self.assertGreater(urgent + shipping, 0)

        self.client.post(self.url, {"action": "release", "count": urgent + shipping + 10})
        state = simulation.load()
        entry = state["rounds"][0]
        self.assertEqual(entry["sources"], {"urgent": urgent, "shipping": shipping, "new": 10})
        released = set(entry["order_nos"])
        self.assertTrue(pools["急單"] | pools["出貨中"] <= released)  # 急單、出貨中先出

        rows = list(load_workbook(BytesIO(self.client.get(reverse("testdata:simulate_round", args=[1])).content),
                                  read_only=True).worksheets[0].iter_rows(values_only=True))
        header = rows[0]
        self.assertEqual({r[header.index("交易序號")] for r in rows[1:]}, released)
        self.assertTrue(all(r[header.index("出貨單號")] for r in rows[1:]))

        self.advance(minutes=60)
        after = self.pools()
        waiting = set().union(*after.values())
        self.assertFalse(waiting & released)  # 出過的不會再出現
        self.assertTrue(set().union(*pools.values()) - released <= waiting)  # 沒出的還在
        self.assertGreater(len(waiting), len(set().union(*pools.values()) - released))  # 加上新流進來的

        self.client.post(self.url, {"action": "undo"})
        state = simulation.load()
        self.assertEqual(state["rounds"], [])
        self.assertFalse(any(o["status"] == "formal" for o in state["orders"]))

    def test_new_orders_are_picked_by_due_date_then_created(self):
        self.start(urgent_pct=0, shipping_pct=0)
        self.advance(to_date="2026-10-05", to_time="16:00")
        state = simulation.load()
        expected = sorted(state["orders"], key=lambda o: (simulation.due_date(o), o["created"], o["order_no"]))[:20]
        self.client.post(self.url, {"action": "release", "count": 20})
        self.assertEqual(simulation.load()["rounds"][0]["order_nos"], [o["order_no"] for o in expected])

    def test_live_mode_catches_up_to_now(self):
        now = timezone.make_aware(datetime(2026, 10, 5, 12, 0))
        with mock.patch("django.utils.timezone.now", return_value=now):
            self.start(live="1")
            self.assertEqual(simulation.load()["clock"], "2026/10/05 12:00:00")
            self.assertNotContains(self.client.get(self.url), "時間往前推")
        later = timezone.make_aware(datetime(2026, 10, 5, 13, 0))
        count = len(simulation.load()["orders"])
        with mock.patch("django.utils.timezone.now", return_value=later):
            self.client.get(self.url)
        state = simulation.load()
        self.assertEqual(state["clock"], "2026/10/05 13:00:00")
        self.assertGreater(len(state["orders"]), count)

    def test_release_only_picks_orders_from_the_last_cut(self):
        self.start()
        self.advance(minutes=60)
        cut = set().union(*self.pools().values())
        self.advance(minutes=60)  # 看統計的時候又流進來的單
        self.assertContains(self.client.get(self.url), "從 10/05 09:00 截斷的單裡挑")
        self.client.post(self.url, {"action": "release", "count": 20000})
        state = simulation.load()
        entry = state["rounds"][0]
        self.assertEqual(set(entry["order_nos"]), cut)
        self.assertEqual(entry["time"], "2026/10/05 09:00:00")
        self.assertTrue(all(o["status"] != "formal" for o in state["orders"] if o["order_no"] not in cut))

    def test_invalid_advance_and_reset(self):
        self.start()
        response = self.advance(to_date="2026-10-05", to_time="07:00")
        self.assertContains(response, "要推進到的時間要晚於目前時間。")
        self.client.post(self.url, {"action": "reset"})
        self.assertIsNone(simulation.load())
        self.assertContains(self.client.get(self.url), "開始一個模擬")
