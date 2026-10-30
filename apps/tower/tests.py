from datetime import timedelta
from unittest import mock
from urllib.parse import quote

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import PagePermission
from apps.accounts.testing import Level, make_user
from apps.orders.tests import xlsx
from apps.personnel.models import Employee
from apps.records.models import Record
from apps.worklog.models import Stage, WorkEntry

from .stats import ALLOCATING, DONE, NOT_STARTED, PICKING, UNREGISTERED, WAIT_ALLOCATION, tower

URL = reverse("tower:index")
NEXT_DAY, NO_PACK = "蝦皮隔日到貨", "蝦皮無包裝"
HEADERS = ["交易平台", "交易序號", "出貨類型", "商品編號", "建立時間"]


def day_rows():
    now = f"{timezone.localdate():%Y/%m/%d} 09:00:00"
    rows = [["蝦皮購物", n, "蝦皮隔日到貨", "A", now] for n in (1, 2, 3, 4)]  # 隔日到 4 張訂單
    rows += [["蝦皮購物", n, "蝦皮無包裝", p, now] for n in (5, 6) for p in "AB"]  # 無包裝 2 張訂單、4 列（非去重 4）
    return rows


class TowerBase(TestCase):
    def setUp(self):
        self.employee = Employee.objects.create(employee_no="E001", name="小明")
        self.client.login(username=make_user("boss", Level.ADMIN).username, password="pw12345!")

    def import_day(self):
        response = self.client.post(
            reverse("daily:day_list"), {"file": xlsx(HEADERS, day_rows(), name="a.xlsx")}
        )
        self.assertEqual(response.status_code, 302)

    def record(self, number, quantity, kind):
        return Record.objects.create(number=number, name="x", quantity=quantity, kind=kind)

    def entry(self, stage, number, ended=False):
        return WorkEntry.objects.create(
            stage=stage, number=number, start_employee=self.employee, ended_at=timezone.now() if ended else None
        )

    def board(self, name):
        return {b.name: b for b in tower()["kinds"]}[name]


class TowerTests(TowerBase):
    def test_always_today_even_with_a_future_batch(self):
        self.import_day()
        self.record("X1", 3, NEXT_DAY)
        with mock.patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(days=1)):
            self.client.post(reverse("daily:day_list"), {"file": xlsx(HEADERS, [["蝦皮購物", 9, "蝦皮隔日到貨", "A", "2030/01/01 09:00:00"]], name="b.xlsx")})
        data = tower()
        self.assertEqual(data["work_date"], timezone.localdate())
        self.assertEqual(self.board(NEXT_DAY).registered, 3)

    def test_totals_come_from_daily_stats_and_unregistered_is_the_gap(self):
        self.import_day()
        self.record("X1", 3, NEXT_DAY)
        board = self.board(NEXT_DAY)
        self.assertEqual((board.total, board.registered, board.states[UNREGISTERED][0], board.over_by), (4, 3, 1, 0))
        self.assertEqual(self.board(NO_PACK).total, 4)  # 無包裝顯示非去重（列數）

    def test_new_batch_raises_total_and_registering_catches_up(self):
        self.import_day()
        self.record("X1", 4, NEXT_DAY)
        self.assertEqual(self.board(NEXT_DAY).states[UNREGISTERED][0], 0)

    def test_states_by_number_ignore_number_format(self):
        self.import_day()
        for number, quantity in [("甲", 1), ("乙", 1), ("丙", 1), ("丁", 1)]:
            self.record(number, quantity, NEXT_DAY)
        self.entry(Stage.PICKING, "乙")  # 撿貨進行中
        self.entry(Stage.PICKING, "丙", ended=True)  # 未配貨
        self.entry(Stage.PICKING, "丁", ended=True)
        self.entry(Stage.ALLOCATION, "丁", ended=True)  # 完成
        board = self.board(NEXT_DAY)
        self.assertEqual(
            {k: tuple(v) for k, v in board.states.items()},
            {UNREGISTERED: (0, 0), NOT_STARTED: (1, 1), PICKING: (1, 1), WAIT_ALLOCATION: (1, 1), ALLOCATING: (0, 0), DONE: (1, 1)},
        )
        self.assertEqual((board.done, board.remaining, board.percent), (1, 3, 25))

    def test_allocation_open_and_repeated_registration_use_latest(self):
        self.import_day()
        self.record("甲", 2, NEXT_DAY)
        self.entry(Stage.PICKING, "甲", ended=True)
        self.entry(Stage.ALLOCATION, "甲")
        self.assertEqual(self.board(NEXT_DAY).states[ALLOCATING], [2, 1])
        self.entry(Stage.ALLOCATION, "甲", ended=True)
        self.assertEqual(self.board(NEXT_DAY).states[DONE], [2, 1])

    def test_over_registered_is_flagged(self):
        self.import_day()
        self.record("X1", 6, NEXT_DAY)
        board = self.board(NEXT_DAY)
        self.assertEqual((board.over_by, board.states[UNREGISTERED][0]), (2, 0))

    def test_unclassified_and_yesterdays_records(self):
        self.import_day()
        self.record("U1", 5, "")
        old = self.record("OLD", 9, NEXT_DAY)
        Record.objects.filter(pk=old.pk).update(created_at=timezone.now() - timezone.timedelta(days=2))
        self.assertEqual(self.board("未分類").registered, 5)
        self.assertEqual(self.board(NEXT_DAY).registered, 0)

    def test_without_daily_stats_shows_registered_only(self):
        self.record("U1", 5, NEXT_DAY)
        board = self.board(NEXT_DAY)
        self.assertEqual((board.total, board.has_total, board.over_by), (5, False, 0))

    def test_active_and_recent(self):
        self.import_day()
        self.record("甲", 1, NEXT_DAY)
        self.record("乙", 1, NEXT_DAY)
        self.entry(Stage.PICKING, "甲")
        self.entry(Stage.PICKING, "乙", ended=True)
        self.entry(Stage.ALLOCATION, "乙", ended=True)
        data = tower()
        self.assertEqual([(e.number, s) for e, s in data["active"]], [("甲", "撿貨")])
        self.assertEqual([e.number for e in data["recent"]], ["乙"])


class TowerPageTests(TestCase):
    def setUp(self):
        PagePermission.objects.create(page_key="data-tower", label="數據塔", min_level=Level.STAFF)
        Record.objects.create(number="X1", quantity=7, name="x", kind="蝦皮其他")
        self.client.login(username=make_user("S001", Level.STAFF).username, password="pw12345!")

    def test_page_and_partial(self):
        self.assertContains(self.client.get(URL), "蝦皮其他")
        partial = self.client.get(URL, {"partial": 1})
        self.assertContains(partial, "已登記 7 / 7")
        self.assertNotContains(partial, "<html")

    def test_needs_page_permission(self):
        PagePermission.objects.all().delete()
        self.assertEqual(self.client.get(URL).status_code, 403)


class KindNamesTests(TowerBase):
    """登記時可選的種類只有今天當日統計有數字卡的；沒有數字卡的不能選。"""

    def test_only_kinds_with_cards_today_are_listed(self):
        from apps.records.rules import kind_names

        self.assertEqual(kind_names(), [])  # 今天還沒匯入當日統計
        self.import_day()
        self.assertEqual(sorted(kind_names()), sorted([NEXT_DAY, NO_PACK]))

    def test_registering_a_kind_without_a_card_is_rejected(self):
        PagePermission.objects.create(page_key="records", label="登記紀錄", min_level=Level.STAFF)
        self.import_day()
        response = self.client.post(reverse("records:list"), {"kind": "其他平台", "number": "A1", "date_text": "", "name": "x", "quantity": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Record.objects.exists())
        self.client.post(reverse("records:list"), {"kind": NEXT_DAY, "number": "A1", "date_text": "", "name": "x", "quantity": "1"})
        self.assertEqual(Record.objects.get().kind, NEXT_DAY)


class TowerDetailTests(TowerBase):
    """數字卡點進去單獨看一個種類；總覽只有緊湊的數字卡，詳細的放在滑鼠停留的小窗。"""

    def setUp(self):
        super().setUp()
        PagePermission.objects.create(page_key="data-tower", label="數據塔", min_level=Level.STAFF)
        self.import_day()
        self.record("甲", 2, NEXT_DAY)
        self.record("乙", 3, NO_PACK)
        self.entry(Stage.PICKING, "甲")
        self.entry(Stage.PICKING, "乙")

    def test_overview_has_tiles_with_links_and_hover_details_but_no_number_list(self):
        response = self.client.get(URL)
        self.assertContains(response, "tower-pop")
        self.assertContains(response, f'href="?kind={quote(NEXT_DAY)}"')
        self.assertNotContains(response, "全部編號")

    def test_detail_shows_only_that_kind(self):
        response = self.client.get(URL, {"kind": NEXT_DAY})
        self.assertContains(response, "全部編號（1）")
        self.assertContains(response, "甲")
        self.assertNotContains(response, "乙")  # 另一個種類的編號、進行中不出現
        self.assertNotContains(response, "tower-pop")
        self.assertContains(response, "回數據塔")

    def test_partial_keeps_the_kind_and_unknown_kind_is_404(self):
        response = self.client.get(URL, {"kind": NEXT_DAY, "partial": 1})
        self.assertContains(response, "全部編號（1）")
        self.assertEqual(self.client.get(URL, {"kind": "不存在"}).status_code, 404)

    def test_refresh_url_carries_the_kind(self):
        response = self.client.get(URL, {"kind": "蝦皮隔日到貨"})
        self.assertIn("kind=", response.context["partial_url"])
