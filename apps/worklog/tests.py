from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import PagePermission
from apps.accounts.testing import Level, make_user
from apps.personnel.models import Employee
from apps.records.models import Record

from .models import Stage, WorkEntry

PICK, ALLOC = "/worklog/picking/", "/worklog/allocation/"


class WorklogTests(TestCase):
    def setUp(self):
        for key, label in [("worklog-picking", "撿貨登記"), ("worklog-allocation", "配貨登記")]:
            PagePermission.objects.create(page_key=key, label=label, min_level=Level.STAFF)
        self.picker = make_user("P001", Level.STAFF)
        self.allocator = make_user("A001", Level.STAFF)
        self.director = make_user("D001", Level.DIRECTOR)
        self.e1 = Employee.objects.create(employee_no="E001", name="小明")
        self.e2 = Employee.objects.create(employee_no="E002", name="小華")
        Record.objects.create(number="N001", name="紙箱", quantity=1)
        self.login(self.picker)

    def login(self, user):
        self.client.login(username=user.username, password="pw12345!")

    def scan(self, url, number, employee_no="E001"):
        return self.client.post(url, {"number": number, "employee_no": employee_no})

    def test_urls(self):
        self.assertEqual(reverse("worklog:picking"), PICK)
        self.assertEqual(reverse("worklog:allocation"), ALLOC)

    def test_each_page_has_its_own_page_permission(self):
        PagePermission.objects.filter(page_key="worklog-allocation").delete()
        self.assertEqual(self.client.get(PICK).status_code, 200)
        self.assertEqual(self.client.get(ALLOC).status_code, 403)

    def test_first_scan_starts_second_ends_third_starts_again(self):
        self.assertRedirects(self.scan(PICK, "N001"), PICK)
        entry = WorkEntry.objects.get()
        self.assertEqual((entry.stage, entry.start_employee, entry.ended_at, entry.created_by), (Stage.PICKING, self.e1, None, self.picker))

        self.scan(PICK, "N001", "E002")
        entry.refresh_from_db()
        self.assertEqual(entry.end_employee, self.e2)
        self.assertIsNotNone(entry.ended_at)

        self.scan(PICK, "N001")
        self.assertEqual(WorkEntry.objects.count(), 2)
        self.assertTrue(WorkEntry.objects.order_by("-pk").first().is_open)

    def test_picking_number_must_be_in_records(self):
        response = self.scan(PICK, "X999")
        self.assertContains(response, "登記紀錄沒有編號「X999」")
        self.assertFalse(WorkEntry.objects.exists())

    def test_employee_must_be_active_personnel(self):
        Employee.objects.create(employee_no="E009", name="離職", is_active=False)
        for employee_no in ["E404", "E009"]:
            self.assertContains(self.scan(PICK, "N001", employee_no), "人員資料沒有在職的員工編號")
        self.assertFalse(WorkEntry.objects.exists())

    def test_allocation_number_must_be_in_picking(self):
        self.login(self.allocator)
        self.assertContains(self.scan(ALLOC, "N001"), "撿貨沒有編號「N001」")
        self.scan(PICK, "N001")
        self.assertRedirects(self.scan(ALLOC, "N001"), ALLOC)
        self.assertEqual(WorkEntry.objects.filter(stage=Stage.ALLOCATION).count(), 1)

    def test_allocation_before_picking_ends_is_anomaly_seen_by_director_only(self):
        self.scan(PICK, "N001")
        self.scan(ALLOC, "N001")
        entry = WorkEntry.objects.get(stage=Stage.ALLOCATION)
        self.assertTrue(entry.anomaly)
        self.assertNotContains(self.client.get(ALLOC), "撿貨未結束")
        self.login(self.director)
        self.assertContains(self.client.get(ALLOC), "撿貨未結束")
        self.assertContains(self.client.get(ALLOC + "?anomaly=1"), "N001")

    def test_allocation_after_picking_ends_is_normal(self):
        self.scan(PICK, "N001")
        self.scan(PICK, "N001")
        self.scan(ALLOC, "N001")
        self.assertFalse(WorkEntry.objects.get(stage=Stage.ALLOCATION).anomaly)

    def test_pages_list_only_their_own_stage(self):
        Record.objects.create(number="N002", name="膠帶", quantity=1)
        self.scan(PICK, "N001")
        self.scan(PICK, "N001")
        self.scan(ALLOC, "N001")
        self.scan(PICK, "N002")
        self.assertContains(self.client.get(ALLOC), "N001")
        self.assertNotContains(self.client.get(ALLOC), "N002")

    def test_edit_numbers_and_employees_but_not_times(self):
        self.scan(PICK, "N001")
        self.scan(PICK, "N001")
        entry = WorkEntry.objects.get()
        started, ended = entry.started_at, entry.ended_at
        Record.objects.create(number="N002", name="膠帶", quantity=1)
        url = reverse("worklog:picking_edit", args=[entry.pk])
        data = {"number": "N002", "start_employee_no": "E002", "end_employee_no": "E002", "started_at": "2000-01-01 00:00"}
        self.assertRedirects(self.client.post(url, data), PICK)
        entry.refresh_from_db()
        self.assertEqual((entry.number, entry.start_employee, entry.end_employee, entry.updated_by), ("N002", self.e2, self.e2, self.picker))
        self.assertEqual((entry.started_at, entry.ended_at), (started, ended))
        self.assertContains(self.client.post(url, {**data, "number": "X999"}), "登記紀錄沒有編號")

    def test_only_own_account_or_director_can_edit_and_delete(self):
        self.scan(PICK, "N001")
        entry = WorkEntry.objects.get()
        self.login(self.allocator)
        self.assertEqual(self.client.get(reverse("worklog:picking_edit", args=[entry.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("worklog:picking_delete", args=[entry.pk])).status_code, 403)
        self.login(self.director)
        self.assertEqual(self.client.get(reverse("worklog:picking_edit", args=[entry.pk])).status_code, 200)
        self.client.post(reverse("worklog:picking_delete", args=[entry.pk]))
        self.assertFalse(WorkEntry.objects.exists())

    def test_entry_of_other_stage_is_not_reachable(self):
        self.scan(PICK, "N001")
        entry = WorkEntry.objects.get()
        self.assertEqual(self.client.get(reverse("worklog:allocation_edit", args=[entry.pk])).status_code, 404)
