from datetime import datetime, time, timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import PagePermission
from apps.accounts.testing import Level, make_user
from apps.orders.tests import xlsx
from apps.personnel.models import Employee
from apps.records.models import Record
from apps.tower.stats import DONE, NOT_STARTED, UNREGISTERED, kind_cards, tower
from apps.worklog.models import Stage, WorkEntry, WorklogSetting
from apps.worklog.rules import scan

from .carry import carry_report
from .models import DayClose
from .workday import current_work_date

NEXT_DAY = "蝦皮隔日到貨"
HEADERS = ["交易平台", "交易序號", "出貨類型", "商品編號", "建立時間"]


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class ClosingBase(TestCase):
    """第一天 = 今天（起算日），之後的日子用 mock 換系統時間。"""

    def setUp(self):
        self.day1 = timezone.localdate()
        self.day2 = self.day1 + timedelta(days=1)
        self.employee = Employee.objects.create(employee_no="E001", name="小明")
        self.boss = make_user("boss", Level.ADMIN)
        self.client.login(username=self.boss.username, password="pw12345!")

    def turn_on(self, start=None):
        setting = WorklogSetting.load()
        setting.carry_start = start or self.day1
        setting.save()

    def now(self, day, hour=10, minute=0):
        return mock.patch("django.utils.timezone.now", return_value=at(day, hour, minute))

    def import_orders(self, day, numbers, name):
        rows = [["蝦皮購物", n, NEXT_DAY, "A", f"{day:%Y/%m/%d} 09:00:00"] for n in numbers]
        response = self.client.post(reverse("daily:day_list"), {"file": xlsx(HEADERS, rows, name=name)})
        self.assertEqual(response.status_code, 302)

    def record(self, number, quantity):
        return Record.objects.create(number=number, name="x", quantity=quantity, kind=NEXT_DAY)

    def close(self):
        response = self.client.post(reverse("closing:close"), {"work_date": current_work_date().isoformat()})
        self.assertEqual(response.status_code, 302)
        return DayClose.objects.order_by("-work_date").first()

    def board(self):
        return {b.name: b for b in tower()["kinds"]}[NEXT_DAY]


class WorkDateTests(ClosingBase):
    def test_without_carry_start_work_date_is_today_and_page_says_off(self):
        self.assertEqual(current_work_date(), self.day1)
        response = self.client.get(reverse("closing:index"))
        self.assertContains(response, "還沒設定結轉起算日")
        self.client.post(reverse("closing:close"), {"work_date": self.day1.isoformat()})
        self.assertFalse(DayClose.objects.exists())

    def test_past_midnight_stays_on_the_open_day_until_closed(self):
        self.turn_on()
        with self.now(self.day1, 10):
            self.import_orders(self.day1, [1, 2], "a.xlsx")
        with self.now(self.day2, 1):  # 做到隔天凌晨 1 點，還沒日結
            self.assertEqual(current_work_date(), self.day1)
            record = self.record("A1", 1)
            self.assertEqual(record.work_date, self.day1)
            self.close()
            self.assertEqual(current_work_date(), self.day2)

    def test_cancel_latest_close_goes_back(self):
        self.turn_on()
        self.import_orders(self.day1, [1], "a.xlsx")
        close = self.close()
        self.assertEqual(current_work_date(), self.day2)
        self.client.post(reverse("closing:cancel", args=[close.work_date]))
        self.assertFalse(DayClose.objects.exists())
        self.assertEqual(current_work_date(), self.day1)

    def test_cannot_close_a_future_day_or_a_stale_page(self):
        self.turn_on()
        self.close()  # 今天日結了，作業日變成明天
        response = self.client.post(reverse("closing:close"), {"work_date": self.day2.isoformat()})
        self.assertEqual(DayClose.objects.count(), 1)
        self.client.post(reverse("closing:close"), {"work_date": self.day1.isoformat()})
        self.assertEqual(DayClose.objects.count(), 1)
        self.assertEqual(response.status_code, 302)

    def test_close_needs_the_level_rule(self):
        self.turn_on()
        staff = make_user("e1")
        PagePermission.objects.create(page_key="day-close", label="日結", min_level=Level.STAFF)
        self.client.login(username=staff.username, password="pw12345!")
        self.assertContains(self.client.get(reverse("closing:index")), "預設主任以上")
        self.assertEqual(self.client.post(reverse("closing:close"), {"work_date": self.day1.isoformat()}).status_code, 403)
        director = make_user("d1", Level.DIRECTOR)
        self.client.login(username=director.username, password="pw12345!")
        self.close()

    def test_carry_start_cannot_be_in_the_past(self):
        url = reverse("worklog_manage:setting")
        response = self.client.post(url, {"rescan_seconds": 10, "carry_start": (self.day1 - timedelta(days=1)).isoformat()})
        self.assertContains(response, "結轉起算日不能早於今天")
        self.client.post(url, {"rescan_seconds": 10, "carry_start": self.day1.isoformat()})
        self.assertEqual(WorklogSetting.load().carry_start, self.day1)


class CarryTests(ClosingBase):
    def first_day(self):
        """第一天：隔日到 4 張，登記 3 張（甲 2、乙 1），乙撿完、甲還沒開始；日結時待印 1、待撿 2、待包 1。"""
        self.turn_on()
        with self.now(self.day1, 10):
            self.import_orders(self.day1, [1, 2, 3, 4], "a.xlsx")
            self.record("甲", 2)
            self.record("乙", 1)
            entry, _ = scan(Stage.PICKING, "乙", self.employee, self.boss)
        with self.now(self.day1, 11):
            scan(Stage.PICKING, "乙", self.employee, self.boss)
        with self.now(self.day1, 18):
            return self.close()

    def test_close_snapshot(self):
        close = self.first_day()
        kind = close.kind(NEXT_DAY)
        self.assertEqual(
            (kind["today"], kind["carried"], kind["done"], kind["unprinted"], kind["picking"], kind["packing"]), (4, 0, 0, 1, 2, 1)
        )
        self.assertContains(self.client.get(reverse("closing:report", args=[self.day1])), "日結報表")

    def test_next_day_board_carries_unfinished(self):
        self.first_day()
        with self.now(self.day2, 9):
            self.assertEqual(current_work_date(), self.day2)
            board = self.board()
            # 今天還沒匯入：總數 = 前日待印 1 + 前日的編號 3
            self.assertEqual((board.total, board.carried, board.today, board.states[UNREGISTERED][0]), (4, 4, 0, 1))
            self.assertEqual(board.prior[NOT_STARTED], 2)
            numbers = {row[0]: row[5] for row in tower()["numbers"]}
            self.assertEqual(numbers, {"甲": self.day1, "乙": self.day1})
            self.import_orders(self.day2, [5, 6], "b.xlsx")
            board = self.board()
            self.assertEqual((board.total, board.today, board.limit), (6, 2, 3))

    def test_registering_takes_the_carried_unprinted_first(self):
        self.first_day()
        with self.now(self.day2, 9):
            self.assertEqual(kind_cards()[1], [(NEXT_DAY, 0, 1)])  # 今天沒匯入，前日待印 1 還是可以登記
            response = self.client.post(reverse("records:list"), {"kind": NEXT_DAY, "number": "丙", "name": "x", "quantity": 2})
            self.assertContains(response, "不能存")
            self.client.post(reverse("records:list"), {"kind": NEXT_DAY, "number": "丙", "name": "x", "quantity": 1})
            board = self.board()
            self.assertEqual((board.states[UNREGISTERED][0], board.prior[UNREGISTERED], board.registered_today), (0, 0, 1))

    def test_done_counts_on_the_day_it_finished(self):
        self.first_day()
        with self.now(self.day2, 9):
            scan(Stage.ALLOCATION, "乙", self.employee, self.boss)
        with self.now(self.day2, 10):
            entry, _ = scan(Stage.ALLOCATION, "乙", self.employee, self.boss)
            self.assertEqual(entry.end_work_date, self.day2)
            board = self.board()
            self.assertEqual((board.done, board.prior[DONE]), (1, 1))
            report = carry_report(self.day2)
            self.assertEqual((report.total, report.left), (4, 3))
            close = self.close()
        self.assertEqual(close.kind(NEXT_DAY)["done"], 1)
        with self.now(self.day2 + timedelta(days=1), 9):
            # 乙在第二天做完，第三天不再出現；甲還沒做、待印 1 繼續轉
            self.assertEqual({row[0] for row in tower()["numbers"]}, {"甲"})
            self.assertEqual(carry_report(current_work_date()).total, 3)

    def test_daily_and_order_pages_show_the_strip(self):
        self.first_day()
        with self.now(self.day2, 9):
            self.import_orders(self.day2, [5, 6], "b.xlsx")
            response = self.client.get(reverse("daily:day_list"))
            self.assertContains(response, "昨日未完成")
            self.assertContains(response, "昨日 4・剩 4")
            self.assertContains(response, "（含前日待印 1）")
            self.assertContains(self.client.get(reverse("tower:index")), "含前日 4")

    def test_overdue_banner(self):
        self.turn_on()
        self.import_orders(self.day1, [1], "a.xlsx")
        with self.now(self.day2, 9):
            self.assertContains(self.client.get(reverse("daily:day_list")), "還沒日結")


class RecordListTests(ClosingBase):
    def test_default_list_is_today_plus_unfinished(self):
        self.turn_on()
        self.import_orders(self.day1, [1, 2, 3], "a.xlsx")
        self.record("舊未完成", 1)
        self.record("舊完成", 1)
        WorkEntry.objects.create(stage=Stage.ALLOCATION, number="舊完成", start_employee=self.employee,
                                 ended_at=timezone.now(), end_work_date=self.day1)
        self.close()
        with self.now(self.day2, 9):
            self.record("今天", 1)
            response = self.client.get(reverse("records:list"))
            numbers = [row["record"].number for row in response.context["rows"]]
            self.assertEqual(sorted(numbers), ["今天", "舊未完成"])
            self.assertContains(response, "未開始")
            all_numbers = [row["record"].number for row in self.client.get(reverse("records:list") + "?scope=all").context["rows"]]
            self.assertIn("舊完成", all_numbers)
            stats = self.client.get(reverse("records:kind_stats")).json()
            self.assertEqual(stats["latest"]["number"], "今天")

    def test_latest_number_only_today(self):
        self.turn_on()
        self.record("A-050", 1)
        self.close()
        with self.now(self.day2, 9):
            stats = self.client.get(reverse("records:kind_stats")).json()
            self.assertIsNone(stats["latest"])
            self.assertEqual(stats["previous"]["number"], "A-050")

    def test_duplicate_number_says_where_it_is(self):
        self.import_orders(self.day1, [1, 2], "a.xlsx")
        self.record("X1", 1)
        response = self.client.post(reverse("records:list"), {"kind": NEXT_DAY, "number": "X1", "name": "y", "quantity": 1})
        self.assertContains(response, f"{self.day1:%m/%d} 登記成「{NEXT_DAY}」")
