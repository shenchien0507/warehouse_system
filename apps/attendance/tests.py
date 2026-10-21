import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Level, PagePermission, Station, User
from apps.personnel.models import Employee, JobTitle

from .models import Attendance, Status

TODAY = timezone.localdate()
YESTERDAY = TODAY - datetime.timedelta(days=1)


def make_user(username, level, department=None):
    return User.objects.create_user(username, password="pw12345!", name=username, level=level, department=department)


class AttendanceTestCase(TestCase):
    def setUp(self):
        self.floor = Department.objects.create(name="現場部")
        self.office = Department.objects.create(name="辦公室")
        self.picking = Station.objects.create(name="撿貨", department=self.floor)
        keeper = JobTitle.objects.create(name="倉管")
        self.e1 = Employee.objects.create(employee_no="P001", name="王小明", department=self.floor, job_title=keeper)
        self.e2 = Employee.objects.create(employee_no="P002", name="李大華", department=self.floor)
        self.e3 = Employee.objects.create(employee_no="P003", name="陳美玲", department=self.office)
        for key in ("attendance-register", "attendance-headcount"):
            PagePermission.objects.create(page_key=key, label=key, min_level=Level.LEADER)

    def login(self, user):
        self.client.login(username=user.username, password="pw12345!")

    def post_rows(self, date, department, rows):
        data = {}
        for employee, values in rows.items():
            for field, value in values.items():
                data[f"e{employee.pk}-{field}"] = value
        url = f"{reverse('attendance:register')}?date={date:%Y-%m-%d}&department={department.pk}"
        return self.client.post(url, data)


class RegisterTests(AttendanceTestCase):
    def test_leader_registers_own_department(self):
        leader = make_user("lead", Level.LEADER, self.floor)
        self.login(leader)
        response = self.client.get(reverse("attendance:register"))
        self.assertContains(response, "王小明")
        self.assertNotContains(response, "陳美玲")
        self.post_rows(TODAY, self.floor, {
            self.e1: {"status": "present", "clock_in": "08:00", "station": self.picking.pk},
            self.e2: {"status": "leave", "clock_in": "08:00"},
        })
        r1 = Attendance.objects.get(employee=self.e1)
        self.assertEqual((r1.status, r1.station, r1.created_by), (Status.PRESENT, self.picking, leader))
        self.assertEqual(r1.clock_in, datetime.time(8, 0))
        # 沒到班不記時間
        self.assertIsNone(Attendance.objects.get(employee=self.e2).clock_in)

    def test_leader_cannot_switch_to_other_department(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.post_rows(TODAY, self.office, {self.e3: {"status": "present"}})
        self.assertFalse(Attendance.objects.filter(employee=self.e3).exists())

    def test_manager_can_register_any_department(self):
        self.login(make_user("mgr", Level.MANAGER))
        self.post_rows(TODAY, self.office, {self.e3: {"status": "present"}})
        self.assertTrue(Attendance.objects.filter(employee=self.e3).exists())

    def test_staff_cannot_use_even_if_page_opened(self):
        PagePermission.objects.filter(page_key="attendance-register").update(min_level=Level.STAFF)
        self.login(make_user("e", Level.STAFF, self.floor))
        self.assertRedirects(self.client.get(reverse("attendance:register")), reverse("home"))

    def test_leader_only_edits_own_records_today(self):
        other = make_user("lead2", Level.LEADER, self.floor)
        Attendance.objects.create(employee=self.e1, date=TODAY, status=Status.PRESENT, created_by=other, updated_by=other)
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.post_rows(TODAY, self.floor, {self.e1: {"status": "absent"}, self.e2: {"status": "present"}})
        self.assertEqual(Attendance.objects.get(employee=self.e1).status, Status.PRESENT)
        self.assertEqual(Attendance.objects.get(employee=self.e2).status, Status.PRESENT)

    def test_past_dates_need_director(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.post_rows(YESTERDAY, self.floor, {self.e1: {"status": "present"}})
        self.assertFalse(Attendance.objects.exists())

        director = make_user("dir", Level.DIRECTOR, self.floor)
        self.login(director)
        self.post_rows(YESTERDAY, self.floor, {self.e1: {"status": "present"}})
        record = Attendance.objects.get()
        self.assertEqual(record.updated_by, director)

    def test_future_dates_rejected(self):
        self.login(make_user("mgr", Level.MANAGER))
        self.post_rows(TODAY + datetime.timedelta(days=1), self.floor, {self.e1: {"status": "present"}})
        self.assertFalse(Attendance.objects.exists())

    def test_clearing_status_deletes_record_and_edit_tracks_updater(self):
        leader = make_user("lead", Level.LEADER, self.floor)
        Attendance.objects.create(employee=self.e1, date=TODAY, status=Status.PRESENT, created_by=leader, updated_by=leader)
        director = make_user("dir", Level.DIRECTOR, self.floor)
        self.login(director)
        self.post_rows(TODAY, self.floor, {self.e1: {"status": "absent"}})
        self.assertEqual(Attendance.objects.get().updated_by, director)
        self.post_rows(TODAY, self.floor, {self.e1: {"status": ""}})
        self.assertFalse(Attendance.objects.exists())

    def test_unchanged_rows_not_saved(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.post_rows(TODAY, self.floor, {self.e1: {"status": ""}})
        self.assertFalse(Attendance.objects.exists())

    def test_inactive_employee_hidden_unless_has_record(self):
        self.e2.is_active = False
        self.e2.save()
        mgr = make_user("mgr", Level.MANAGER)
        self.login(mgr)
        url = f"{reverse('attendance:register')}?department={self.floor.pk}"
        self.assertNotContains(self.client.get(url), "李大華")
        Attendance.objects.create(employee=self.e2, date=TODAY, status=Status.PRESENT, created_by=mgr, updated_by=mgr)
        self.assertContains(self.client.get(url), "李大華")


class HeadcountTests(AttendanceTestCase):
    def test_counts_by_department_and_station(self):
        mgr = make_user("mgr", Level.MANAGER)
        office_desk = Station.objects.create(name="櫃台", department=self.office)
        Attendance.objects.create(employee=self.e1, date=TODAY, status=Status.PRESENT, station=self.picking, created_by=mgr, updated_by=mgr)
        Attendance.objects.create(employee=self.e2, date=TODAY, status=Status.PRESENT, station=office_desk, created_by=mgr, updated_by=mgr)
        self.login(mgr)
        response = self.client.get(reverse("attendance:headcount"))
        floor = next(row for row in response.context["summary"] if row["department"] == self.floor)
        self.assertEqual((floor["active"], floor["present"], floor["unregistered"]), (2, 2, 0))
        self.assertEqual(floor["stations"], [("撿貨", 1), ("辦公室／櫃台", 1)])
        office = next(row for row in response.context["summary"] if row["department"] == self.office)
        self.assertEqual((office["present"], office["unregistered"]), (0, 1))
        self.assertEqual(response.context["total_present"], 2)

    def test_leader_sees_only_own_department(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        response = self.client.get(reverse("attendance:headcount"))
        self.assertEqual([row["department"] for row in response.context["summary"]], [self.floor])
