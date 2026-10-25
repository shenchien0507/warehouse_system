import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils.http import urlencode
from django.utils import timezone

from apps.accounts.models import Department, PagePermission, Station, User
from apps.accounts.testing import Level, make_user
from apps.personnel.models import Employee

from .models import Attendance, AttendanceEvent, ClockSetting, EventKind, StationBatch, StationEditLock, Status
from .records import add_event, now_minute

FLEX_FIELDS = ("clock_in_early", "clock_in_late", "clock_out_early", "clock_out_late")
TODAY = timezone.localdate()
YESTERDAY = TODAY - datetime.timedelta(days=1)
MIDNIGHT = datetime.time(0, 0)  # 今天一定已經過了的時間，測試今天的紀錄用


def t(value):
    return datetime.time.fromisoformat(value)



class AttendanceTestCase(TestCase):
    def setUp(self):
        self.floor = Department.objects.create(name="現場部")
        self.office = Department.objects.create(name="辦公室")
        self.picking = Station.objects.create(name="撿貨")
        self.e1 = Employee.objects.create(employee_no="P001", name="王小明", department=self.floor)
        self.e2 = Employee.objects.create(employee_no="P002", name="李大華", department=self.floor)
        self.e3 = Employee.objects.create(employee_no="P003", name="陳美玲", department=self.office)
        for key in ("attendance-register", "attendance-headcount", "attendance-stations"):
            PagePermission.objects.create(page_key=key, label=key, min_level=Level.LEADER)
        self.mgr = make_user("mgr", Level.MANAGER)
        # 彈性 12 小時：任何時間都能按上班、下班，時段限制另外測
        ClockSetting.objects.create(pk=1, **{f: 720 for f in FLEX_FIELDS})

    def login(self, user):
        self.client.login(username=user.username, password="pw12345!")

    def event(self, employee, kind, time=MIDNIGHT, date=TODAY, user=None, end_time=None):
        record, error = add_event(employee, date, user or self.mgr, kind, time, end_time)
        self.assertEqual(error, "")
        return record

    def register_url(self, employee, date=TODAY):
        return f"{reverse('attendance:register')}?{urlencode({'employee_no': employee.employee_no, 'date': f'{date:%Y-%m-%d}'})}"

    def press(self, employee, action, date=TODAY):
        return self.client.post(self.register_url(employee, date), {"action": action})

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
        self.assertContains(response, "現場部／員工")
        self.assertNotContains(self.client.get(reverse("attendance:register")), "現場部／員工")

    def test_lookup_by_name_or_partial_employee_no(self):
        self.login(self.mgr)
        url = reverse("attendance:register")
        response = self.client.get(f"{url}?employee_no=小明")
        self.assertEqual((response.context["employee"], response.context["employee_no"]), (self.e1, "P001"))
        self.assertEqual(self.client.get(f"{url}?{urlencode({'employee_no': 'P002 李大華'})}").context["employee"], self.e2)
        response = self.client.get(f"{url}?employee_no=P00")
        self.assertIsNone(response.context["employee"])
        self.assertEqual([c.name for c in response.context["candidates"]], ["王小明", "李大華", "陳美玲"])
        self.assertContains(response, "請選一位")
        # 組長只找得到自己部門的人
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.assertEqual([c.name for c in self.client.get(f"{url}?employee_no=P00").context["candidates"]], ["王小明", "李大華"])
        self.assertContains(self.client.get(f"{url}?employee_no=美玲"), "找不到工號或姓名")

    def test_unknown_employee_no(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.assertContains(self.client.get(f"{reverse('attendance:register')}?employee_no=NOPE"), "找不到工號")

    def test_clock_in_then_clock_out(self):
        leader = make_user("lead", Level.LEADER, self.floor)
        self.login(leader)
        response = self.press(self.e1, "clock_in")
        self.assertNotIn("employee_no", response["Location"])  # 回到空白工號欄，登記下一位
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

    def test_leave_while_on_site_means_leaving_then_back(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.press(self.e1, "clock_in")
        self.assertEqual(self.press(self.e1, "leave_out").status_code, 302)
        self.assertEqual(len(self.kinds(self.e1)), 1)  # 沒有請假離開按鈕，送來也不處理
        self.add(self.e1, kind="leave", time=f"{now_minute():%H:%M}", note="看醫生")
        record = Attendance.objects.get()
        self.assertEqual((record.status, record.on_site, record.clock_out), (Status.PARTIAL, False, now_minute()))
        self.assertEqual(AttendanceEvent.objects.get(kind=EventKind.LEAVE).note, "看醫生")
        self.press(self.e1, "clock_in")
        record.refresh_from_db()
        self.assertTrue(record.on_site)
        self.assertEqual(len(self.kinds(self.e1)), 3)

    def test_leave_rules_depend_on_being_on_site(self):
        self.event(self.e1, EventKind.CLOCK_IN, t("08:00"), YESTERDAY)
        # 上班前的請假（例如上午請假、下午才來）不算離開
        self.assertTrue(self.event(self.e1, EventKind.LEAVE, t("06:00"), YESTERDAY, end_time=t("07:00")).on_site)
        # 全天請假沒有開始時間，也不算離開
        self.assertTrue(self.event(self.e1, EventKind.LEAVE, None, YESTERDAY).on_site)
        # 今天在現場的人，不能先登記還沒到的請假
        self.event(self.e2, EventKind.CLOCK_IN)
        later = (datetime.datetime.combine(TODAY, now_minute()) + datetime.timedelta(minutes=1)).time()
        if later > now_minute():  # 23:59 時跳過
            _, error = add_event(self.e2, TODAY, self.mgr, EventKind.LEAVE, later)
            self.assertIn("還在現場", error)
        # 還沒上班的人可以先登記之後的請假
        _, error = add_event(self.e3, TODAY, self.mgr, EventKind.LEAVE, t("23:59"))
        self.assertEqual(error, "")

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
        self.add(self.e1, YESTERDAY, kind="leave", time="12:00", note="家裡有事")
        self.assertContains(self.add(self.e1, YESTERDAY, kind="clock_out", time="13:00"), "還沒有上班")  # 請假時已經離開
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
    def summary(self, user, date=TODAY):
        self.login(user)
        return self.client.get(f"{reverse('attendance:register')}?date={date:%Y-%m-%d}").context["summary"]

    def test_expected_arrived_missing(self):
        e4 = Employee.objects.create(employee_no="P004", name="張三", department=self.floor)
        e5 = Employee.objects.create(employee_no="P005", name="離職", department=self.floor, is_active=False)
        self.event(self.e1, EventKind.CLOCK_IN)
        # 李大華上午請假、下午有來又離開：算實到
        self.event(self.e2, EventKind.LEAVE, time=None, end_time=t("00:00"))
        self.event(self.e2, EventKind.CLOCK_IN)
        self.event(self.e2, EventKind.CLOCK_OUT)
        # 陳美玲全天請假、張三缺勤：都算未到
        self.event(self.e3, EventKind.LEAVE, time=None)
        self.event(e4, EventKind.ABSENT, time=None)
        self.event(e5, EventKind.CLOCK_IN)  # 離職的人不算應到，也不算實到
        self.login(self.mgr)
        self.assertContains(self.client.get(reverse("attendance:register")), "應到")
        self.assertEqual(self.summary(self.mgr), {"expected": 4, "arrived": 2, "missing": 2, "on_site": 1})

    def test_unregistered_and_voided_count_as_missing(self):
        record = self.event(self.e1, EventKind.CLOCK_IN)
        AttendanceEvent.objects.update(voided_at=timezone.now(), voided_by=self.mgr)
        record.refresh()
        record.save()
        self.assertEqual(self.summary(self.mgr), {"expected": 3, "arrived": 0, "missing": 3, "on_site": 0})

    def test_scope_follows_register_rules(self):
        Employee.objects.create(employee_no="P009", name="無部門")
        self.event(self.e3, EventKind.CLOCK_IN)
        self.assertEqual(self.summary(self.mgr)["expected"], 4)  # 經理含未設定部門
        self.assertEqual(self.summary(make_user("lead", Level.LEADER, self.floor)), {"expected": 2, "arrived": 0, "missing": 2, "on_site": 0})

    def test_reminds_missing_clock_out(self):
        self.event(self.e1, EventKind.CLOCK_IN, date=YESTERDAY)
        self.event(self.e3, EventKind.CLOCK_IN, date=YESTERDAY)
        self.event(self.e2, EventKind.CLOCK_IN, date=YESTERDAY)
        self.event(self.e2, EventKind.CLOCK_OUT, time=t("01:00"), date=YESTERDAY)
        self.login(make_user("lead", Level.LEADER, self.floor))
        response = self.client.get(reverse("attendance:register"))
        self.assertEqual([r.employee for r in response.context["missing_clock_out"]], [self.e1])
        self.assertContains(response, "沒有下班紀錄")
        self.assertContains(response, "請通知主管處理")

    def test_old_headcount_url_redirects(self):
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.assertRedirects(self.client.get(reverse("attendance:headcount")), reverse("attendance:register"))


class PersonListTests(AttendanceTestCase):
    def setUp(self):
        super().setUp()
        self.event(self.e1, EventKind.CLOCK_IN)
        self.event(self.e2, EventKind.LEAVE, time=None)

    def url(self, kind, date=TODAY):
        return f"{reverse('attendance:list')}?{urlencode({'date': f'{date:%Y-%m-%d}', 'kind': kind})}"

    def names(self, user, kind):
        self.login(user)
        return [r["employee"].name for r in self.client.get(self.url(kind)).context["rows"]]

    def test_lists_by_kind_across_departments(self):
        for kind, names in {
            "expected": ["王小明", "李大華", "陳美玲"],
            "arrived": ["王小明"],
            "missing": ["李大華", "陳美玲"],
            "on_site": ["王小明"],
        }.items():
            self.assertEqual(self.names(self.mgr, kind), names, kind)
        response = self.client.get(self.url("missing"))
        self.assertContains(response, "辦公室")  # 部門欄
        self.assertContains(response, "employee_no=P002")

    def test_left_people_still_arrived(self):
        self.event(self.e1, EventKind.CLOCK_OUT)
        self.assertEqual(self.names(self.mgr, "arrived"), ["王小明"])
        self.assertEqual(self.names(self.mgr, "on_site"), [])
        self.assertContains(self.client.get(self.url("arrived")), "已離開")

    def test_leader_only_own_department(self):
        leader = make_user("lead", Level.LEADER, self.floor)
        self.assertEqual(self.names(leader, "expected"), ["王小明", "李大華"])
        self.assertEqual(self.client.get(self.url("bogus")).status_code, 404)

    def test_clock_in_and_out_from_list(self):
        e4 = Employee.objects.create(employee_no="P004", name="張三", department=self.floor)
        self.login(make_user("lead", Level.LEADER, self.floor))
        url = self.url("expected")
        self.assertContains(self.client.get(url), "勾選的人上班")
        # 勾選多人上班：已在場的王小明會被擋下，張三上班；請假的李大華可以上班（變部分請假）
        response = self.client.post(url, {"do": "clock_in", "employee": [self.e1.pk, self.e2.pk, e4.pk, self.e3.pk]})
        self.assertRedirects(response, url)
        on_site = set(Attendance.objects.filter(on_site=True).values_list("employee__name", flat=True))
        self.assertEqual(on_site, {"王小明", "李大華", "張三"})  # 陳美玲不在組長的範圍，不處理
        self.assertEqual(Attendance.objects.get(employee=self.e2).status, Status.PARTIAL)
        # 每列的按鈕只處理那個人
        self.client.post(url, {"do": f"clock_out:{e4.pk}", "employee": [self.e1.pk]})
        on_site = set(Attendance.objects.filter(on_site=True).values_list("employee__name", flat=True))
        self.assertEqual(on_site, {"王小明", "李大華"})
        self.assertContains(self.client.post(url, {"do": "clock_out"}, follow=True), "請先勾選人員")

    def test_list_past_date_has_no_clock_buttons(self):
        url = self.url("expected", YESTERDAY)
        self.login(self.mgr)
        self.assertNotContains(self.client.get(url), "勾選的人上班")
        self.assertEqual(self.client.post(url, {"do": "clock_in", "employee": [self.e1.pk]}).status_code, 403)


class StationTestCase(AttendanceTestCase):
    def setUp(self):
        super().setUp()
        self.desk = Station.objects.create(name="櫃台")
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


class StationAssignTests(StationTestCase):
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
        self.event(self.e1, EventKind.LEAVE)
        self.login(self.mgr)
        self.assertNotContains(self.client.get(self.url), "王小明")
        self.event(self.e3, EventKind.CLOCK_IN, t("08:00"), YESTERDAY)
        self.event(self.e3, EventKind.LEAVE, t("12:00"), YESTERDAY)
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
        self.assertContains(preview, "確認建立安排")
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

    def test_no_change_creates_no_batch_but_first_batch_can_be_saved_as_is(self):
        self.post(None, action="confirm")
        self.assertEqual(StationBatch.objects.count(), 1)
        self.post(None, action="confirm")
        self.assertEqual(StationBatch.objects.count(), 1)

    def test_someone_left_without_station_changes_can_still_create_batch(self):
        self.event(self.e3, EventKind.CLOCK_IN)
        self.login(self.mgr)
        self.confirm_all(self.picking)
        self.event(self.e1, EventKind.LEAVE)
        e3 = Attendance.objects.get(employee=self.e3)
        data = {f"a{e3.pk}-station": self.picking.pk}
        preview = self.client.post(self.url, data)
        self.assertContains(preview, "離開：王小明")
        self.assertContains(preview, "其他人的工位都不變")
        self.client.post(self.url, {**data, "action": "confirm"})
        latest = StationBatch.objects.first()
        self.assertEqual([e.employee for e in latest.entries.all()], [self.e3])
        self.assertEqual(self.client.get(self.list_url).context["changes"], [])

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
        self.event(self.e1, EventKind.LEAVE)
        self.client.post(self.url, {f"a{Attendance.objects.get(employee=self.e3).pk}-station": self.picking.pk, "action": "confirm"})
        diff = self.client.get(self.list_url).context["batches"][0]["diff"]
        self.assertEqual((diff["delta"], diff["left"], diff["moved"]), (-1, [self.e1], 1))

    def test_alert_lists_changes_after_current_batch(self):
        self.login(self.mgr)
        self.confirm_all(self.picking)
        self.assertEqual(self.client.get(self.list_url).context["changes"], [])
        self.event(self.e1, EventKind.LEAVE)
        self.event(self.e3, EventKind.CLOCK_IN)
        response = self.client.get(self.list_url)
        self.assertEqual(
            [(c["kind"], c["text"]) for c in response.context["changes"]],
            [("out", "王小明（現場部） 請假"), ("in", "陳美玲（辦公室） 上班")],
        )
        self.assertContains(response, "）相比，有 2 人異動，現場目前 1 人")
        # 組長只看到自己部門的異動
        self.login(make_user("lead", Level.LEADER, self.floor))
        self.assertEqual([c["kind"] for c in self.client.get(self.list_url).context["changes"]], ["out"])

    def test_timeline_orders_events_and_batches_with_counts(self):
        director = make_user("dir", Level.DIRECTOR, self.floor)
        e4 = Employee.objects.create(employee_no="P004", name="張志強", department=self.floor)
        self.event(self.e1, EventKind.CLOCK_IN, t("08:00"), YESTERDAY)
        self.event(e4, EventKind.CLOCK_IN, t("08:00"), YESTERDAY)
        self.event(self.e2, EventKind.LEAVE, None, YESTERDAY, end_time=t("12:00"))
        self.event(self.e1, EventKind.LEAVE, t("11:00"), YESTERDAY)
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
                (t("11:00"), "out", "王小明（現場部） 請假 11:00 起", 1),
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


class StationBoardTests(StationTestCase):
    """各工位人數、編輯鎖、各部門分開排、已離開標灰。"""

    def setUp(self):
        super().setUp()
        self.lead_floor = make_user("lead", Level.LEADER, self.floor)
        self.lead_office = make_user("lead_office", Level.LEADER, self.office)

    def test_station_counts_for_people_on_site(self):
        self.event(self.e3, EventKind.CLOCK_IN)
        e4 = Employee.objects.create(employee_no="P004", name="張志強", department=self.floor)
        self.event(e4, EventKind.CLOCK_IN)
        self.login(self.mgr)
        data = {f"a{a.pk}-station": "" for a in Attendance.objects.filter(on_site=True)}
        data[f"a{self.a1.pk}-station"] = self.picking.pk
        data[f"a{Attendance.objects.get(employee=self.e3).pk}-station"] = self.picking.pk
        self.client.post(self.url, {**data, "action": "confirm"})
        response = self.client.get(self.list_url)
        self.assertEqual(response.context["stations"], [("撿貨", 2), ("未安排", 1)])
        self.assertEqual(response.context["batches"][0]["stations"], [("撿貨", 2), ("未安排", 1)])
        self.assertContains(response, "目前在場各工位")
        # 有人離開後，目前在場的工位人數跟著變
        self.event(self.e1, EventKind.CLOCK_OUT)
        self.assertEqual(self.client.get(self.list_url).context["stations"], [("撿貨", 1), ("未安排", 1)])

    def test_people_who_left_are_greyed_in_current_batch(self):
        self.login(self.mgr)
        self.confirm_all(self.picking)
        self.event(self.e1, EventKind.CLOCK_OUT, now_minute())
        response = self.client.get(self.list_url)
        entry = response.context["batches"][0]["entries"][0]
        self.assertTrue(entry.gone)
        self.assertContains(response, f"已離開 {now_minute():%H:%M}")

    def test_only_one_account_can_edit_at_a_time(self):
        self.login(self.mgr)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.login(self.lead_floor)
        response = self.client.get(self.url, follow=True)
        self.assertRedirects(response, self.list_url)
        self.assertContains(response, "正在編輯工位安排")
        self.assertContains(response, "編輯中</button>")
        self.assertFalse(response.context["can_create"])
        self.post(self.picking, action="confirm", user=self.lead_floor)
        self.assertFalse(StationBatch.objects.exists())
        # 同一個帳號可以重新進入；確認後放開，別人就能編輯
        self.post(self.desk, action="confirm", user=self.mgr)
        self.assertEqual(StationBatch.objects.count(), 1)
        self.login(self.lead_floor)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_leaving_without_saving_releases_lock(self):
        self.login(self.mgr)
        self.client.get(self.url)
        self.client.post(self.url, {"action": "release"})
        self.login(self.lead_floor)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.post(reverse("attendance:station_lock"), {"action": "release"})
        self.login(self.mgr)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_lock_expires_and_touch_keeps_it(self):
        self.login(self.mgr)
        self.client.get(self.url)
        touch = self.client.post(reverse("attendance:station_lock"), {"action": "touch", "date": f"{TODAY:%Y-%m-%d}"})
        self.assertEqual(touch.json(), {"ok": True})
        StationEditLock.objects.update(touched_at=timezone.now() - datetime.timedelta(minutes=StationEditLock.LOCK_MINUTES + 1))
        self.login(self.lead_floor)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.login(self.mgr)
        touch = self.client.post(reverse("attendance:station_lock"), {"action": "touch", "date": f"{TODAY:%Y-%m-%d}"})
        self.assertEqual(touch.json(), {"ok": False})

    def test_force_unlock_needs_all_departments_rule(self):
        self.login(self.lead_floor)
        self.client.get(self.url)
        self.login(self.lead_office)
        self.assertEqual(self.client.post(reverse("attendance:station_lock"), {"action": "force"}).status_code, 403)
        self.login(self.mgr)
        self.assertContains(self.client.get(self.list_url), "強制解除")
        self.client.post(reverse("attendance:station_lock"), {"action": "force", "date": f"{TODAY:%Y-%m-%d}"})
        self.assertFalse(StationEditLock.objects.exists())
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_departments_arranged_separately_do_not_overwrite_each_other(self):
        self.event(self.e3, EventKind.CLOCK_IN)
        e3 = Attendance.objects.get(employee=self.e3)
        self.post(self.picking, action="confirm", user=self.lead_floor)
        self.login(self.lead_office)
        self.client.post(self.url, {f"a{e3.pk}-station": self.desk.pk, "action": "confirm"})
        latest = StationBatch.objects.first()
        self.assertEqual({(e.employee, e.station) for e in latest.entries.all()}, {(self.e1, self.picking), (self.e3, self.desk)})
        self.login(self.mgr)
        response = self.client.get(self.list_url)
        self.assertEqual(response.context["changes"], [])
        self.assertEqual(response.context["batches"][0]["total"], 2)
        # 組長看不到別的部門建立、但自己部門沒變的批次
        self.login(self.lead_floor)
        self.assertEqual(len(self.client.get(self.list_url).context["batches"]), 1)
        items = self.client.get(f"{self.list_url}&view=timeline").context["timeline"]
        self.assertEqual(len([i for i in items if i["kind"] == "batch"]), 1)


class ClockWindowTests(AttendanceTestCase):
    """上下班時間：上班、下班按鈕只在設定時段內可按，其他時間只能補登。"""

    def set_window(self, clock_in_open, clock_out_open):
        now = datetime.datetime.combine(TODAY, now_minute())
        far = (now + datetime.timedelta(hours=6)).time()
        ClockSetting.objects.filter(pk=1).update(
            work_start=now.time() if clock_in_open else far, work_end=now.time() if clock_out_open else far, **{f: 10 for f in FLEX_FIELDS},
        )

    def test_buttons_blocked_outside_window(self):
        self.set_window(clock_in_open=False, clock_out_open=False)
        self.login(self.mgr)
        response = self.client.get(self.register_url(self.e1))
        self.assertContains(response, 'value="clock_in" class="btn btn-success btn-lg flex-fill" disabled')
        self.assertContains(response, "其他時間、中途請假請用下方「補登紀錄」")
        response = self.press(self.e1, "clock_in")
        self.assertFalse(Attendance.objects.exists())
        self.assertContains(self.client.get(response["Location"]), "上班按鈕只在")
        # 補登不受限制
        self.add(self.e1, kind="clock_in", time=f"{now_minute():%H:%M}")
        self.assertEqual(Attendance.objects.get().status, Status.PRESENT)

    def test_clock_in_window_only(self):
        self.set_window(clock_in_open=True, clock_out_open=False)
        self.login(self.mgr)
        self.press(self.e1, "clock_in")
        self.assertTrue(Attendance.objects.get().on_site)
        self.press(self.e1, "clock_out")
        self.assertTrue(Attendance.objects.get().on_site)

    def test_list_buttons_follow_window(self):
        self.set_window(clock_in_open=False, clock_out_open=True)
        self.login(self.mgr)
        url = f"{reverse('attendance:list')}?{urlencode({'date': f'{TODAY:%Y-%m-%d}', 'kind': 'expected'})}"
        response = self.client.get(url)
        self.assertNotContains(response, "勾選的人上班")
        self.assertNotContains(response, f'value="clock_in:{self.e1.pk}"')
        self.client.post(url, {"do": "clock_in", "employee": [self.e1.pk]})
        self.assertFalse(Attendance.objects.exists())

    def test_window_wraps_midnight(self):
        setting = ClockSetting(work_start=t("00:10"), work_end=t("23:50"), **{f: 30 for f in FLEX_FIELDS})
        self.assertTrue(setting.allows(EventKind.CLOCK_IN, t("23:45")))
        self.assertTrue(setting.allows(EventKind.CLOCK_OUT, t("00:15")))
        self.assertFalse(setting.allows(EventKind.CLOCK_IN, t("00:41")))
        self.assertEqual(setting.describe(EventKind.CLOCK_IN), "23:40–00:40")

    def test_early_and_late_set_separately(self):
        setting = ClockSetting(
            work_start=t("08:00"), clock_in_early=30, clock_in_late=5, work_end=t("17:00"), clock_out_early=0, clock_out_late=60,
        )
        self.assertEqual((setting.describe(EventKind.CLOCK_IN), setting.describe(EventKind.CLOCK_OUT)), ("07:30–08:05", "17:00–18:00"))
        self.assertTrue(setting.allows(EventKind.CLOCK_IN, t("07:30")))
        self.assertFalse(setting.allows(EventKind.CLOCK_IN, t("08:06")))
        self.assertFalse(setting.allows(EventKind.CLOCK_OUT, t("16:59")))
        self.assertTrue(setting.allows(EventKind.CLOCK_OUT, t("18:00")))

    def test_setting_page_uses_24h(self):
        self.client.force_login(make_user("boss", Level.ADMIN))
        url = reverse("attendance_manage:clock_setting")
        response = self.client.get(url)
        self.assertContains(response, 'placeholder="HH:MM"')
        self.assertNotContains(response, 'type="time"')
        data = {"work_start": "07:30", "clock_in_early": 15, "clock_in_late": 5, "work_end": "17:30", "clock_out_early": 0, "clock_out_late": 30}
        response = self.client.post(url, data, follow=True)
        self.assertContains(response, "上班按鈕 07:15–07:35 可按，下班按鈕 17:30–18:00 可按")
        setting = ClockSetting.load()
        self.assertEqual((setting.work_start, setting.clock_in_late, setting.work_end, setting.clock_out_late), (t("07:30"), 5, t("17:30"), 30))
        self.assertContains(self.client.post(url, {**data, "work_start": "5:30 PM"}), "輸入有效的時間")
        # 非管理員、沒開放頁面權限的人不能進
        self.login(self.mgr)
        self.assertEqual(self.client.get(url).status_code, 403)
