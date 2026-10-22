import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils.http import urlencode
from django.utils import timezone

from apps.accounts.models import Department, Level, PagePermission, Station, User
from apps.personnel.models import Employee, JobTitle

from .models import Attendance, AttendanceEvent, EventKind, StationBatch, Status
from .records import add_event

TODAY = timezone.localdate()
YESTERDAY = TODAY - datetime.timedelta(days=1)
MIDNIGHT = datetime.time(0, 0)  # 今天一定已經過了的時間，測試今天的紀錄用


def t(value):
    return datetime.time.fromisoformat(value)


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
        for key in ("attendance-register", "attendance-headcount", "attendance-stations"):
            PagePermission.objects.create(page_key=key, label=key, min_level=Level.LEADER)
        self.mgr = make_user("mgr", Level.MANAGER)

    def login(self, user):
        self.client.login(username=user.username, password="pw12345!")

    def event(self, employee, kind, time=MIDNIGHT, date=TODAY, user=None, end_time=None):
        record, error = add_event(employee, date, user or self.mgr, kind, time, end_time)
        self.assertEqual(error, "")
        return record

    def register_url(self, employee, date=TODAY):
        return f"{reverse('attendance:register')}?{urlencode({'employee_no': employee.employee_no, 'date': f'{date:%Y-%m-%d}'})}"

    def press(self, employee, action, date=TODAY, note=""):
        return self.client.post(self.register_url(employee, date), {"action": action, "quick_note": note})

    def add(self, employee, date=TODAY, **values):
        data = {f"e-{key}": value for key, value in values.items()}
        return self.client.post(self.register_url(employee, date), {"action": "add", **data})

    def kinds(self, employee, date=TODAY):
        return [(e.kind, e.voided_at is not None) for e in AttendanceEvent.objects.filter(attendance__employee=employee, attendance__date=date)]


class RegisterTests(AttendanceTestCase):
    def test_lookup_by_employee_no_shows_info(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        response = self.client.get(self.register_url(self.e1))
        self.assertContains(response, "王小明")
        self.assertContains(response, "倉管")
        self.assertNotContains(self.client.get(reverse("attendance:register")), "王小明")

    def test_unknown_employee_no(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.assertContains(self.client.get(f"{reverse('attendance:register')}?employee_no=NOPE"), "找不到工號")

    def test_clock_in_then_clock_out(self):
        leader = make_user("lead", Level.LEADER, self.floor)
        self.login(leader)
        response = self.press(self.e1, "clock_in")
        self.assertIn("employee_no=P001", response["Location"])
        record = Attendance.objects.get(employee=self.e1)
        self.assertEqual((record.status, record.on_site, record.created_by), (Status.PRESENT, True, leader))
        self.assertIsNotNone(record.clock_in)
        self.press(self.e1, "clock_out")
        record.refresh_from_db()
        self.assertEqual((record.status, record.on_site), (Status.PRESENT, False))
        self.assertIsNotNone(record.clock_out)
        self.assertEqual(self.kinds(self.e1), [(EventKind.CLOCK_IN, False), (EventKind.CLOCK_OUT, False)])

    def test_morning_leave_then_afternoon_clock_in_keeps_both(self):
        # 早上主管登記請假，下午由另一位組長幫他按上班：請假那筆還在，狀態是部分請假
        lead1 = make_user("lead1", Level.LEADER, self.floor)
        self.event(self.e1, EventKind.LEAVE, time=None, end_time=t("12:00"), user=lead1)
        self.assertEqual(Attendance.objects.get().status, Status.LEAVE)
        self.login(make_user("lead2", Level.LEADER, self.floor))
        self.press(self.e1, "clock_in")
        record = Attendance.objects.get()
        self.assertEqual((record.status, record.on_site), (Status.PARTIAL, True))
        self.assertEqual(self.kinds(self.e1), [(EventKind.LEAVE, False), (EventKind.CLOCK_IN, False)])

    def test_leave_out_with_reason_then_back(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.press(self.e1, "clock_in")
        self.press(self.e1, "leave_out", note="看醫生")
        record = Attendance.objects.get()
        self.assertEqual((record.status, record.on_site), (Status.PARTIAL, False))
        self.assertEqual(AttendanceEvent.objects.get(kind=EventKind.LEAVE_OUT).note, "看醫生")
        self.press(self.e1, "clock_in")
        record.refresh_from_db()
        self.assertTrue(record.on_site)
        self.assertEqual(len(self.kinds(self.e1)), 3)

    def test_second_clock_in_and_clock_out_without_clock_in_rejected(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.press(self.e1, "clock_out")
        self.assertFalse(Attendance.objects.exists())
        self.press(self.e1, "clock_in")
        response = self.press(self.e1, "clock_in")
        self.assertEqual(AttendanceEvent.objects.count(), 1)
        self.assertContains(self.client.get(response["Location"]), "還沒離開")

    def test_add_with_time_returns_to_search_and_validates(self):
        director = make_user("dir", Level.DIRECTOR, self.floor)
        self.login(director)
        response = self.add(self.e1, YESTERDAY, kind="clock_in", time="08:00")
        self.assertRedirects(response, f"{reverse('attendance:register')}?{urlencode({'date': f'{YESTERDAY:%Y-%m-%d}'})}")
        # 時間不能早於上一筆進出；請假結束要晚於開始；上班要填時間
        self.assertContains(self.add(self.e1, YESTERDAY, kind="clock_out", time="07:00"), "不能早於上一筆")
        self.assertContains(self.add(self.e1, YESTERDAY, kind="leave", time="13:00", end_time="12:00"), "結束時間要晚於開始時間")
        self.assertContains(self.add(self.e2, YESTERDAY, kind="clock_in"), "請填時間")
        self.add(self.e1, YESTERDAY, kind="leave_out", time="12:00", note="家裡有事")
        self.add(self.e1, YESTERDAY, kind="leave", time="12:00")
        record = Attendance.objects.get(employee=self.e1)
        self.assertEqual((record.status, record.clock_in, record.clock_out), (Status.PARTIAL, t("08:00"), t("12:00")))

    def test_future_time_today_rejected(self):
        self.login(self.mgr)
        late = (timezone.localtime() + datetime.timedelta(minutes=5)).time()
        if late < timezone.localtime().time():  # 快跨日時跳過
            return
        self.assertContains(self.add(self.e1, kind="clock_in", time=f"{late:%H:%M}"), "還沒到的時間")

    def test_absent_conflicts(self):
        self.login(self.mgr)
        self.add(self.e1, kind="absent")
        self.assertEqual(Attendance.objects.get().status, Status.ABSENT)
        self.press(self.e1, "clock_in")
        self.assertEqual(AttendanceEvent.objects.count(), 1)
        self.press(self.e2, "clock_in")
        self.assertContains(self.add(self.e2, kind="absent"), "不能標記缺勤")

    def test_void_recomputes_status_and_keeps_history(self):
        leader = make_user("lead", Level.LEADER, self.floor)
        self.login(leader)
        self.press(self.e1, "clock_in")
        event = AttendanceEvent.objects.get()
        self.client.post(self.register_url(self.e1), {"action": "void", "event": event.pk})
        event.refresh_from_db()
        self.assertEqual(event.voided_by, leader)
        record = Attendance.objects.get()
        self.assertEqual((record.status, record.on_site), ("", False))
        self.assertContains(self.client.get(self.register_url(self.e1)), "已作廢")

    def test_only_own_events_voided_today_director_any(self):
        other = make_user("lead2", Level.LEADER, self.floor)
        record = self.event(self.e1, EventKind.CLOCK_IN, user=other)
        event = record.events.get()
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.assertEqual(self.client.post(self.register_url(self.e1), {"action": "void", "event": event.pk}).status_code, 403)
        self.login(make_user("dir", Level.DIRECTOR, self.floor))
        self.client.post(self.register_url(self.e1), {"action": "void", "event": event.pk})
        self.assertIsNotNone(AttendanceEvent.objects.get().voided_at)

    def test_leader_limited_to_own_department(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.assertContains(self.client.get(self.register_url(self.e3)), "不在你可以登記的範圍")
        self.press(self.e3, "clock_in")
        self.assertFalse(Attendance.objects.exists())

    def test_manager_can_register_any_department(self):
        self.login(self.mgr)
        self.press(self.e3, "clock_in")
        self.assertTrue(Attendance.objects.filter(employee=self.e3).exists())

    def test_staff_cannot_use_even_if_page_opened(self):
        PagePermission.objects.filter(page_key="attendance-register").update(min_level=Level.STAFF)
        self.login(make_user("e", Level.STAFF, self.floor))
        self.assertRedirects(self.client.get(reverse("attendance:register")), reverse("home"))

    def test_past_dates_need_director_and_no_quick_buttons(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.assertEqual(self.add(self.e1, YESTERDAY, kind="clock_in", time="08:00").status_code, 403)
        self.assertFalse(Attendance.objects.exists())
        self.login(make_user("dir", Level.DIRECTOR, self.floor))
        self.press(self.e1, "clock_in", YESTERDAY)
        self.assertFalse(Attendance.objects.exists())

    def test_future_dates_rejected(self):
        self.login(self.mgr)
        tomorrow = TODAY + datetime.timedelta(days=1)
        self.assertEqual(self.add(self.e1, tomorrow, kind="leave").status_code, 403)
        self.assertFalse(Attendance.objects.exists())

    def test_inactive_employee_only_with_existing_record(self):
        self.e2.is_active = False
        self.e2.save()
        self.login(self.mgr)
        self.assertContains(self.client.get(self.register_url(self.e2)), "已離職，不能登記")
        self.press(self.e2, "clock_in")
        self.assertFalse(Attendance.objects.exists())
        self.event(self.e2, EventKind.CLOCK_IN)
        self.assertContains(self.client.get(self.register_url(self.e2)), "李大華")


class HeadcountTests(AttendanceTestCase):
    def summary(self, user):
        self.login(user)
        return self.client.get(reverse("attendance:register")).context["summary"]

    def test_counts_by_department_status_and_station(self):
        office_desk = Station.objects.create(name="櫃台", department=self.office)
        Attendance.objects.filter(pk=self.event(self.e1, EventKind.CLOCK_IN).pk).update(station=self.picking)
        self.event(self.e2, EventKind.LEAVE, time=None, end_time=t("00:00"))
        record = self.event(self.e2, EventKind.CLOCK_IN)
        self.event(self.e2, EventKind.CLOCK_OUT)
        Attendance.objects.filter(pk=record.pk).update(station=office_desk)
        self.login(self.mgr)
        response = self.client.get(reverse("attendance:register"))
        self.assertContains(response, "到班人數")
        self.assertEqual((response.context["total_present"], response.context["total_on_site"]), (2, 1))
        floor = next(row for row in response.context["summary"] if row["department"] == self.floor)
        self.assertEqual(
            (floor["active"], floor["present"], floor["partial"], floor["leave"], floor["on_site"], floor["unregistered"]), (2, 2, 1, 0, 1, 0)
        )
        self.assertEqual([(st["label"], st["count"]) for st in floor["stations"]], [("撿貨", 1), ("辦公室／櫃台", 1)])
        office = next(row for row in response.context["summary"] if row["department"] == self.office)
        self.assertEqual((office["present"], office["unregistered"]), (0, 1))

    def test_all_voided_counts_as_unregistered(self):
        record = self.event(self.e1, EventKind.CLOCK_IN)
        AttendanceEvent.objects.update(voided_at=timezone.now(), voided_by=self.mgr)
        record.refresh()
        record.save()
        floor = next(row for row in self.summary(self.mgr) if row["department"] == self.floor)
        self.assertEqual((floor["present"], floor["unregistered"]), (0, 2))

    def test_leader_sees_only_own_department(self):
        summary = self.summary(make_user("lead", Level.LEADER, self.floor))
        self.assertEqual([row["department"] for row in summary], [self.floor])

    def test_manager_sees_employees_without_department(self):
        Employee.objects.create(employee_no="P009", name="無部門")
        summary = self.summary(self.mgr)
        none_row = next(row for row in summary if row["department"] is None)
        self.assertEqual((none_row["label"], none_row["active"], none_row["unregistered"]), ("未設定部門", 1, 1))
        self.assertNotIn(None, [row["department"] for row in self.summary(make_user("lead", Level.LEADER, self.floor))])

    def test_old_headcount_url_redirects(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.assertRedirects(self.client.get(reverse("attendance:headcount")), reverse("attendance:register"))


class PersonListTests(AttendanceTestCase):
    def setUp(self):
        super().setUp()
        Attendance.objects.filter(pk=self.event(self.e1, EventKind.CLOCK_IN).pk).update(station=self.picking)
        self.event(self.e2, EventKind.LEAVE, time=None)

    def get(self, user, **params):
        self.login(user)
        params.setdefault("date", f"{TODAY:%Y-%m-%d}")
        return self.client.get(f"{reverse('attendance:list')}?{urlencode(params)}")

    def test_lists_by_kind(self):
        for kind, names in {
            "active": ["王小明", "李大華"],
            "present": ["王小明"],
            "partial": [],
            "leave": ["李大華"],
            "absent": [],
            "on_site": ["王小明"],
            "unregistered": [],
        }.items():
            response = self.get(self.mgr, department=self.floor.pk, kind=kind)
            self.assertEqual([r["employee"].name for r in response.context["rows"]], names, kind)
        self.assertEqual([r["employee"].name for r in self.get(self.mgr, department=self.office.pk, kind="unregistered").context["rows"]], ["陳美玲"])

    def test_list_by_station_and_link_to_register(self):
        response = self.get(self.mgr, department=self.floor.pk, kind="station", station=self.picking.pk)
        self.assertEqual([r["employee"].name for r in response.context["rows"]], ["王小明"])
        self.assertContains(response, "employee_no=P001")
        self.assertEqual(self.get(self.mgr, department=self.floor.pk, kind="station", station="none").context["rows"], [])

    def test_leader_cannot_list_other_department(self):
        leader = make_user("lead", Level.LEADER, self.floor)
        self.assertEqual(self.get(leader, department=self.office.pk, kind="active").status_code, 404)
        self.assertEqual(self.get(leader, department=self.floor.pk, kind="bogus").status_code, 404)
        self.assertEqual(self.get(leader, department=self.floor.pk, kind="active").status_code, 200)


class StationAssignTests(AttendanceTestCase):
    def setUp(self):
        super().setUp()
        self.desk = Station.objects.create(name="櫃台", department=self.office)
        self.a1 = self.event(self.e1, EventKind.CLOCK_IN)
        self.event(self.e2, EventKind.LEAVE, time=None)
        self.list_url = f"{reverse('attendance:stations')}?date={TODAY:%Y-%m-%d}"
        self.url = f"{reverse('attendance:station_new')}?date={TODAY:%Y-%m-%d}"

    def post(self, station, action=None, user=None, url=None):
        self.login(user or self.mgr)
        data = {f"a{self.a1.pk}-station": station.pk if station else ""}
        if action:
            data["action"] = action
        return self.client.post(url or self.url, data)

    def confirm_all(self, station):
        data = {f"a{a.pk}-station": station.pk for a in Attendance.objects.filter(on_site=True)}
        self.client.post(self.url, {**data, "action": "confirm"})

    def test_index_does_not_expand_list_and_has_create_button(self):
        self.login(self.mgr)
        response = self.client.get(self.list_url)
        self.assertNotContains(response, "王小明")
        self.assertContains(response, "建立安排")
        self.assertContains(response, "還沒有建立安排")

    def test_create_page_lists_people_on_site_across_departments(self):
        self.event(self.e3, EventKind.CLOCK_IN)
        self.login(self.mgr)
        response = self.client.get(self.url)
        self.assertContains(response, "王小明")
        self.assertContains(response, "陳美玲")
        self.assertNotContains(response, "李大華")

    def test_people_who_left_are_not_listed_today_but_are_for_past_dates(self):
        self.event(self.e1, EventKind.LEAVE_OUT)
        self.login(self.mgr)
        self.assertNotContains(self.client.get(self.url), "王小明")
        self.event(self.e3, EventKind.CLOCK_IN, t("08:00"), YESTERDAY)
        self.event(self.e3, EventKind.LEAVE_OUT, t("12:00"), YESTERDAY)
        response = self.client.get(f"{reverse('attendance:station_new')}?date={YESTERDAY:%Y-%m-%d}")
        self.assertContains(response, "陳美玲")
        self.assertContains(response, "12:00 離開")

    def test_non_manager_only_sees_own_department(self):
        self.event(self.e3, EventKind.CLOCK_IN)
        self.login(make_user("lead", Level.LEADER, self.floor))
        response = self.client.get(self.url)
        self.assertContains(response, "王小明")
        self.assertNotContains(response, "陳美玲")

    def test_change_needs_confirmation_then_creates_batch(self):
        preview = self.post(self.picking)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "確認修改")
        self.a1.refresh_from_db()
        self.assertIsNone(self.a1.station)
        self.assertFalse(StationBatch.objects.exists())
        self.assertRedirects(self.post(self.picking, action="confirm"), self.list_url)
        self.a1.refresh_from_db()
        self.assertEqual((self.a1.station, self.a1.updated_by), (self.picking, self.mgr))
        batch = StationBatch.objects.get()
        self.assertEqual((batch.date, batch.created_by), (TODAY, self.mgr))
        entry = batch.entries.get()
        self.assertEqual((entry.employee, entry.station), (self.e1, self.picking))

    def test_no_change_creates_no_batch(self):
        self.post(None, action="confirm")
        self.assertFalse(StationBatch.objects.exists())

    def test_index_shows_batches_with_counts_and_diff(self):
        self.event(self.e3, EventKind.CLOCK_IN)
        self.login(self.mgr)
        self.confirm_all(self.picking)
        self.confirm_all(self.desk)
        response = self.client.get(self.list_url)
        batches = response.context["batches"]
        self.assertEqual(len(batches), 2)
        self.assertTrue(batches[0]["current"])
        self.assertEqual(batches[0]["departments"], [("現場部", 1), ("辦公室", 1)])
        self.assertEqual({e.station for e in batches[0]["entries"]}, {self.desk})
        self.assertEqual(batches[0]["diff"], {"delta": 0, "left": [], "arrived": [], "moved": 2})
        self.assertIsNone(batches[1]["diff"])
        self.assertContains(response, "目前生效")
        self.assertContains(response, "當天第一批")
        # 王小明離開後再排一批：差別顯示離開一人
        self.event(self.e1, EventKind.LEAVE_OUT)
        self.client.post(self.url, {f"a{Attendance.objects.get(employee=self.e3).pk}-station": self.picking.pk, "action": "confirm"})
        diff = self.client.get(self.list_url).context["batches"][0]["diff"]
        self.assertEqual((diff["delta"], diff["left"], diff["moved"]), (-1, [self.e1], 1))

    def test_alert_lists_changes_after_current_batch(self):
        self.login(self.mgr)
        self.confirm_all(self.picking)
        self.assertEqual(self.client.get(self.list_url).context["changes"], [])
        self.event(self.e1, EventKind.LEAVE_OUT)
        self.event(self.e3, EventKind.CLOCK_IN)
        response = self.client.get(self.list_url)
        self.assertEqual(
            [(c["kind"], c["text"]) for c in response.context["changes"]],
            [("out", "王小明（現場部） 請假離開"), ("in", "陳美玲（辦公室） 上班")],
        )
        self.assertContains(response, "有 2 人異動，現場目前 1 人")
        # 組長只看到自己部門的異動
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.assertEqual([c["kind"] for c in self.client.get(self.list_url).context["changes"]], ["out"])

    def test_timeline_orders_events_and_batches_with_counts(self):
        director = make_user("dir", Level.DIRECTOR, self.floor)
        e4 = Employee.objects.create(employee_no="P004", name="張志強", department=self.floor)
        self.event(self.e1, EventKind.CLOCK_IN, t("08:00"), YESTERDAY)
        self.event(e4, EventKind.CLOCK_IN, t("08:00"), YESTERDAY)
        self.event(self.e2, EventKind.LEAVE, None, YESTERDAY, end_time=t("12:00"))
        self.event(self.e1, EventKind.LEAVE_OUT, t("11:00"), YESTERDAY)
        self.event(self.e2, EventKind.CLOCK_IN, t("13:00"), YESTERDAY)
        batch = StationBatch.objects.create(date=YESTERDAY, created_by=director)
        StationBatch.objects.filter(pk=batch.pk).update(
            created_at=timezone.make_aware(datetime.datetime.combine(YESTERDAY, t("10:30")))
        )
        batch.entries.create(employee=self.e1)
        batch.entries.create(employee=e4)
        self.login(director)
        items = self.client.get(f"{reverse('attendance:stations')}?date={YESTERDAY:%Y-%m-%d}&view=timeline").context["timeline"]
        self.assertEqual(
            [(i["time"], i["kind"], i["text"], i["count"]) for i in items],
            [
                (None, "leave", "李大華（現場部） 請假 至 12:00", 0),
                (t("08:00"), "in", "2 人上班", 2),
                (t("10:30"), "batch", "建立安排（2 人）", 2),
                (t("11:00"), "out", "王小明（現場部） 請假離開", 1),
                (t("13:00"), "in", "李大華（現場部） 上班", 2),
            ],
        )
        self.assertTrue(items[2]["current"])

    def test_leader_only_sees_own_department_in_batches(self):
        self.event(self.e3, EventKind.CLOCK_IN)
        self.login(self.mgr)
        self.confirm_all(self.picking)
        self.login(make_user("lead", Level.LEADER, self.floor))
        batches = self.client.get(self.list_url).context["batches"]
        self.assertEqual(batches[0]["departments"], [("現場部", 1)])
        self.login(make_user("lead_office", Level.LEADER, self.office))
        self.assertEqual(self.client.get(self.list_url).context["batches"][0]["departments"], [("辦公室", 1)])

    def test_any_station_can_be_assigned_and_cleared(self):
        self.post(self.desk, action="confirm")
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.station, self.desk)
        self.post(None, action="confirm")
        self.a1.refresh_from_db()
        self.assertIsNone(self.a1.station)

    def test_page_permission_decides_access(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        PagePermission.objects.filter(page_key="attendance-stations").update(min_level=Level.DIRECTOR)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_past_needs_director_and_future_rejected(self):
        past = self.event(self.e1, EventKind.CLOCK_IN, t("08:00"), YESTERDAY)
        past_url = f"{reverse('attendance:station_new')}?date={YESTERDAY:%Y-%m-%d}"
        data = {f"a{past.pk}-station": self.picking.pk, "action": "confirm"}
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.assertEqual(self.client.get(past_url).status_code, 403)
        self.assertEqual(self.client.post(past_url, data).status_code, 403)
        self.login(make_user("dir", Level.DIRECTOR, self.floor))
        self.client.post(past_url, data)
        past.refresh_from_db()
        self.assertEqual(past.station, self.picking)
        future = f"{reverse('attendance:station_new')}?date={TODAY + datetime.timedelta(days=1):%Y-%m-%d}"
        self.assertEqual(self.client.post(future, {"action": "confirm"}).status_code, 403)
        self.assertNotContains(self.client.get(f"{reverse('attendance:stations')}?date={TODAY + datetime.timedelta(days=1):%Y-%m-%d}"), "建立安排</a>")
