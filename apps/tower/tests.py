from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import PagePermission
from apps.accounts.testing import Level, make_user
from apps.personnel.models import Employee
from apps.records.models import Record
from apps.worklog.models import Stage, WorkEntry

from .stats import ALLOCATING, DONE, NOT_STARTED, PICKING, WAIT_ALLOCATION, parse_number, tower

URL = reverse("tower:index")


class ParseNumberTests(TestCase):
    def test_formats(self):
        self.assertEqual(parse_number("261030-001"), (date(2026, 10, 30), "normal"))
        self.assertEqual(parse_number("261030-W01"), (date(2026, 10, 30), "unpackaged"))
        self.assertEqual(parse_number("261030-w12"), (date(2026, 10, 30), "unpackaged"))

    def test_bad_formats_are_none(self):
        for number in ["N001", "261030001", "261330-001", "261030-A01", "261030-"]:
            self.assertIsNone(parse_number(number), number)


class TowerStatsTests(TestCase):
    def setUp(self):
        self.employee = Employee.objects.create(employee_no="E001", name="小明")
        for number, quantity in [
            ("261029-001", 99),  # 前一天，不算
            ("261030-001", 10),
            ("261030-002", 20),
            ("261030-003", 30),
            ("261030-004", 40),
            ("261030-005", 50),
            ("261030-W01", 300),
            ("261030-W02", 200),
            ("BAD", 5),
        ]:
            Record.objects.create(number=number, quantity=quantity, name="x")

    def entry(self, stage, number, ended=False):
        return WorkEntry.objects.create(
            stage=stage, number=number, start_employee=self.employee, ended_at=timezone.now() if ended else None
        )

    def states(self, board):
        return {key: tuple(value) for key, value in board.states.items()}

    def test_states_and_totals_per_kind(self):
        self.entry(Stage.PICKING, "261030-002")  # 撿貨進行中
        self.entry(Stage.PICKING, "261030-003", ended=True)  # 未配貨
        self.entry(Stage.PICKING, "261030-004", ended=True)
        self.entry(Stage.ALLOCATION, "261030-004")  # 配貨進行中
        self.entry(Stage.PICKING, "261030-005", ended=True)
        self.entry(Stage.ALLOCATION, "261030-005", ended=True)  # 完成
        self.entry(Stage.PICKING, "261030-W01", ended=True)
        self.entry(Stage.ALLOCATION, "261030-W01", ended=True)

        data = tower()
        self.assertEqual(data["work_date"], date(2026, 10, 30))
        self.assertEqual(data["skipped"], 1)
        normal, unpackaged = data["kinds"]
        self.assertEqual((normal.total, normal.count, normal.done, normal.remaining), (150, 5, 50, 100))
        self.assertEqual(
            self.states(normal),
            {NOT_STARTED: (10, 1), PICKING: (20, 1), WAIT_ALLOCATION: (30, 1), ALLOCATING: (40, 1), DONE: (50, 1)},
        )
        self.assertEqual((unpackaged.total, unpackaged.done, unpackaged.remaining), (500, 300, 200))
        self.assertEqual(unpackaged.states[NOT_STARTED], [200, 1])

    def test_repeated_registration_uses_latest_entry(self):
        self.entry(Stage.PICKING, "261030-001", ended=True)
        self.entry(Stage.PICKING, "261030-001")  # 又刷了一次，現在是進行中
        board = tower()["kinds"][0]
        self.assertEqual(board.states[PICKING], [10, 1])
        self.assertEqual(board.states[WAIT_ALLOCATION], [0, 0])

    def test_active_and_recent(self):
        self.entry(Stage.PICKING, "261030-002")
        self.entry(Stage.ALLOCATION, "261030-001", ended=True)
        data = tower()
        self.assertEqual([(e.number, stage) for e, stage in data["active"]], [("261030-002", "撿貨")])
        self.assertEqual([e.number for e in data["recent"]], ["261030-001"])

    def test_no_records(self):
        Record.objects.all().delete()
        self.assertIsNone(tower()["work_date"])


class TowerPageTests(TestCase):
    def setUp(self):
        PagePermission.objects.create(page_key="data-tower", label="數據塔", min_level=Level.STAFF)
        Record.objects.create(number="261030-001", quantity=7, name="x")
        self.client.login(username=make_user("S001", Level.STAFF).username, password="pw12345!")

    def test_page_and_partial(self):
        response = self.client.get(URL)
        self.assertContains(response, "2026/10/30")
        self.assertContains(response, "一般配")
        partial = self.client.get(URL, {"partial": 1})
        self.assertContains(partial, "一般配")
        self.assertNotContains(partial, "<html")

    def test_needs_page_permission(self):
        PagePermission.objects.all().delete()
        self.assertEqual(self.client.get(URL).status_code, 403)
