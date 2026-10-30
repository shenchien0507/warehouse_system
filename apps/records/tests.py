from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import PagePermission
from apps.accounts.testing import Level, make_user

from .forms import FIELDS
from .models import Record


def grid_data(*rows, total=3):
    """多列輸入的表單資料；rows 是 (編號, 日期, 名稱, 數量)，其餘列空白。"""
    data = {"form-TOTAL_FORMS": total, "form-INITIAL_FORMS": 0, "form-MIN_NUM_FORMS": 0, "form-MAX_NUM_FORMS": 500}
    for i, row in enumerate(rows):
        data.update({f"form-{i}-{field}": value for field, value in zip(FIELDS, row)})
    return data


class RecordTests(TestCase):
    def setUp(self):
        PagePermission.objects.create(page_key="records", label="登記紀錄", min_level=Level.STAFF)
        self.staff = make_user("S001", Level.STAFF)
        self.other = make_user("S002", Level.STAFF)
        self.director = make_user("D001", Level.DIRECTOR)
        self.login(self.staff)

    def login(self, user):
        self.client.login(username=user.username, password="pw12345!")

    def record(self, user, **values):
        return Record.objects.create(**{"number": "A001", "name": "紙箱", "quantity": 1, "created_by": user, **values})

    def test_page_needs_page_permission(self):
        PagePermission.objects.all().delete()
        self.assertEqual(self.client.get(reverse("records:list")).status_code, 403)
        self.login(make_user("boss", Level.ADMIN))
        self.assertEqual(self.client.get(reverse("records:list")).status_code, 200)

    def test_grid_saves_filled_rows_with_logged_in_operator(self):
        response = self.client.post(
            reverse("records:new"), grid_data(("A001", "10/30 早上", "紙箱", "5"), ("A002", "", "膠帶", "-2"), total=10)
        )
        self.assertRedirects(response, reverse("records:list"))
        rows = list(Record.objects.order_by("number").values_list("number", "date_text", "name", "quantity", "created_by"))
        self.assertEqual(rows, [("A001", "10/30 早上", "紙箱", 5, self.staff.pk), ("A002", "", "膠帶", -2, self.staff.pk)])

    def test_date_is_stored_as_typed(self):
        self.client.post(reverse("records:new"), grid_data(("1", "隨便打 2026/13/45", "x", "1")))
        self.assertEqual(Record.objects.get().date_text, "隨便打 2026/13/45")

    def test_grid_rejects_non_numeric_quantity_and_saves_nothing(self):
        response = self.client.post(reverse("records:new"), grid_data(("A001", "", "紙箱", "5"), ("A002", "", "膠帶", "3箱")))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "數量只能輸入整數")
        self.assertFalse(Record.objects.exists())

    def test_grid_requires_number_and_name_on_partly_filled_rows(self):
        response = self.client.post(reverse("records:new"), grid_data(("", "", "紙箱", "5")))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Record.objects.exists())

    def test_empty_grid_is_an_error(self):
        response = self.client.post(reverse("records:new"), grid_data())
        self.assertContains(response, "沒有輸入任何資料")

    def test_list_shows_everyone_but_edit_buttons_only_on_own_records(self):
        mine, theirs = self.record(self.staff, number="M1"), self.record(self.other, number="T1")
        response = self.client.get(reverse("records:list"))
        self.assertContains(response, "T1")
        self.assertContains(response, reverse("records:edit", args=[mine.pk]))
        self.assertNotContains(response, reverse("records:edit", args=[theirs.pk]))

    def test_staff_edits_own_record_but_not_others(self):
        mine, theirs = self.record(self.staff), self.record(self.other)
        data = {"number": "B9", "date_text": "改過", "name": "新名稱", "quantity": "7"}
        self.assertRedirects(self.client.post(reverse("records:edit", args=[mine.pk]), data), reverse("records:list"))
        mine.refresh_from_db()
        self.assertEqual((mine.number, mine.quantity, mine.created_by, mine.updated_by), ("B9", 7, self.staff, self.staff))
        self.assertEqual(self.client.post(reverse("records:edit", args=[theirs.pk]), data).status_code, 403)
        self.assertEqual(self.client.post(reverse("records:delete", args=[theirs.pk])).status_code, 403)
        self.assertTrue(Record.objects.filter(pk=theirs.pk).exists())

    def test_director_edits_and_deletes_others_records_operator_stays(self):
        theirs = self.record(self.other)
        self.login(self.director)
        data = {"number": "A001", "date_text": "", "name": "紙箱", "quantity": "2"}
        self.client.post(reverse("records:edit", args=[theirs.pk]), data)
        theirs.refresh_from_db()
        self.assertEqual((theirs.quantity, theirs.created_by, theirs.updated_by), (2, self.other, self.director))
        self.client.post(reverse("records:delete", args=[theirs.pk]))
        self.assertFalse(Record.objects.exists())

    def test_delete_own_record_ignores_outside_next_url(self):
        mine = self.record(self.staff)
        response = self.client.post(reverse("records:delete", args=[mine.pk]), {"next": "https://evil.example/"})
        self.assertRedirects(response, reverse("records:list"))
        self.assertFalse(Record.objects.exists())

    def test_search(self):
        self.record(self.staff, number="A001", name="紙箱")
        self.record(self.other, number="Z999", name="膠帶")
        response = self.client.get(reverse("records:list"), {"q": "膠帶"})
        self.assertContains(response, "Z999")
        self.assertNotContains(response, "A001")
