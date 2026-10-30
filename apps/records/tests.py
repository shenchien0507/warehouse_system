from urllib.parse import quote

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import PagePermission
from apps.accounts.testing import Level, make_user

from .forms import FIELDS
from .models import Record


KIND = "蝦皮其他"  # 預設統計分組裡有的種類


def grid_data(*rows, total=3):
    """多列輸入的表單資料；rows 是 (編號, 日期, 名稱, 數量)，其餘列空白。"""
    data = {"kind": KIND, "form-TOTAL_FORMS": total, "form-INITIAL_FORMS": 0, "form-MIN_NUM_FORMS": 0, "form-MAX_NUM_FORMS": 500}
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
        number = f"N{Record.objects.count() + 1:03d}"
        return Record.objects.create(**{"number": number, "name": "紙箱", "quantity": 1, "created_by": user, **values})

    def test_page_needs_page_permission(self):
        PagePermission.objects.all().delete()
        self.assertEqual(self.client.get(reverse("records:list")).status_code, 403)
        self.login(make_user("boss", Level.ADMIN))
        self.assertEqual(self.client.get(reverse("records:list")).status_code, 200)

    def test_grid_saves_filled_rows_with_logged_in_operator(self):
        response = self.client.post(
            reverse("records:new"), grid_data(("A001", "10/30 早上", "紙箱", "5"), ("A002", "", "膠帶", "-2"), total=10)
        )
        self.assertRedirects(response, reverse("records:list") + "?kind=" + quote(KIND))
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

    def test_number_must_be_unique(self):
        self.record(self.other, number="A001")
        response = self.client.post(reverse("records:new"), grid_data(("A002", "", "膠帶", "1"), ("A001", "", "紙箱", "1")))
        self.assertContains(response, "這個編號已經登記過了")
        self.assertEqual(Record.objects.count(), 1)

        response = self.client.post(reverse("records:new"), grid_data(("B1", "", "x", "1"), ("B1", "", "y", "1")))
        self.assertContains(response, "和第 1 列的編號重複")
        self.assertEqual(Record.objects.count(), 1)

        mine = self.record(self.staff, number="M1")
        data = {"number": "A001", "date_text": "", "name": "紙箱", "quantity": "1"}
        self.assertContains(self.client.post(reverse("records:edit", args=[mine.pk]), data), "這個編號已經登記過了")
        data["number"] = "M1"  # 改其他欄、編號不變可以存
        self.assertRedirects(self.client.post(reverse("records:edit", args=[mine.pk]), data), reverse("records:list"))

    def bulk_edit_data(self, records, **changes):
        """批量修改的表單資料；changes 是 {紀錄: {欄位: 值}}。"""
        data = {"form-TOTAL_FORMS": len(records), "form-INITIAL_FORMS": len(records), "form-MIN_NUM_FORMS": 0, "form-MAX_NUM_FORMS": 500}
        for i, record in enumerate(records):
            values = {"id": record.pk, "number": record.number, "date_text": record.date_text, "name": record.name, "quantity": record.quantity}
            values.update(changes.get(record.number, {}))
            data.update({f"form-{i}-{key}": value for key, value in values.items()})
        return data

    def bulk_edit_url(self, *records):
        return reverse("records:bulk_edit") + "?" + "&".join(f"ids={r.pk}" for r in records)

    def test_bulk_edit_changes_only_changed_rows(self):
        a, b = self.record(self.staff, number="A1"), self.record(self.staff, number="A2")
        url = self.bulk_edit_url(a, b)
        self.assertContains(self.client.get(url), "批量修改")
        response = self.client.post(url, self.bulk_edit_data([a, b], A2={"name": "改名", "quantity": "9"}))
        self.assertRedirects(response, reverse("records:list"))
        a.refresh_from_db(), b.refresh_from_db()
        self.assertEqual((b.name, b.quantity, b.updated_by, b.created_by), ("改名", 9, self.staff, self.staff))
        self.assertIsNone(a.updated_by)

    def test_bulk_edit_rejects_duplicate_numbers_in_batch(self):
        a, b = self.record(self.staff, number="A1"), self.record(self.staff, number="A2")
        url = self.bulk_edit_url(a, b)
        response = self.client.post(url, self.bulk_edit_data([a, b], A2={"number": "A1"}))
        self.assertEqual(response.status_code, 200)
        b.refresh_from_db()
        self.assertEqual(b.number, "A2")

    def test_bulk_edit_only_lists_own_records_for_staff(self):
        mine, theirs = self.record(self.staff, number="M1"), self.record(self.other, number="T1")
        response = self.client.get(self.bulk_edit_url(mine, theirs))
        self.assertContains(response, 'value="M1"')
        self.assertNotContains(response, 'value="T1"')
        self.assertRedirects(self.client.get(self.bulk_edit_url(theirs)), reverse("records:list"))

    def test_bulk_delete(self):
        a, b, c = (self.record(self.staff, number=n) for n in ("A1", "A2", "A3"))
        response = self.client.post(reverse("records:bulk_delete"), {"ids": [a.pk, b.pk]})
        self.assertRedirects(response, reverse("records:list"))
        self.assertEqual(list(Record.objects.values_list("number", flat=True)), ["A3"])

    def test_bulk_delete_refuses_others_records(self):
        mine, theirs = self.record(self.staff), self.record(self.other)
        response = self.client.post(reverse("records:bulk_delete"), {"ids": [mine.pk, theirs.pk]})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Record.objects.count(), 2)
        self.login(self.director)
        self.client.post(reverse("records:bulk_delete"), {"ids": [mine.pk, theirs.pk]})
        self.assertFalse(Record.objects.exists())

    def test_list_has_checkboxes_only_for_editable_records(self):
        mine, theirs = self.record(self.staff), self.record(self.other)
        response = self.client.get(reverse("records:list"))
        self.assertContains(response, f'name="ids" value="{mine.pk}"')
        self.assertNotContains(response, f'name="ids" value="{theirs.pk}"')

    def test_quick_add_saves_one_record_and_returns_to_list(self):
        url = reverse("records:list") + "?q=A"
        response = self.client.post(url, {"kind": KIND, "number": "A1", "date_text": "早班", "name": "紙箱", "quantity": "3"})
        self.assertRedirects(response, url)
        record = Record.objects.get()
        self.assertEqual(
            (record.number, record.date_text, record.quantity, record.created_by, record.kind), ("A1", "早班", 3, self.staff, KIND)
        )

    def test_quick_add_errors_stay_on_page(self):
        self.record(self.other, number="A1")
        response = self.client.post(reverse("records:list"), {"kind": KIND, "number": "A1", "date_text": "", "name": "紙箱", "quantity": "x"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "這個編號已經登記過了")
        self.assertContains(response, "數量只能輸入整數")
        self.assertContains(response, 'value="紙箱"')
        self.assertEqual(Record.objects.count(), 1)

    def test_new_registration_needs_a_kind(self):
        response = self.client.post(reverse("records:list"), {"number": "A1", "date_text": "", "name": "紙箱", "quantity": "3"})
        self.assertContains(response, "請先選種類")
        response = self.client.post(reverse("records:new"), {**grid_data(("A2", "", "紙箱", "1")), "kind": ""})
        self.assertContains(response, "請先選種類")
        response = self.client.post(reverse("records:list"), {"kind": "不存在", "number": "A1", "date_text": "", "name": "紙箱", "quantity": "3"})
        self.assertFalse(Record.objects.exists())

    def test_grid_gives_every_row_the_chosen_kind(self):
        response = self.client.post(reverse("records:new"), grid_data(("A1", "", "紙箱", "1"), ("A2", "", "膠帶", "2")))
        self.assertRedirects(response, reverse("records:list") + "?kind=" + quote(KIND))
        self.assertEqual(set(Record.objects.values_list("kind", flat=True)), {KIND})

    def test_list_keeps_showing_every_record_and_kind_from_url_is_preselected(self):
        self.record(self.staff, number="A1", kind="蝦皮無包裝")
        self.record(self.other, number="A2", kind="")
        response = self.client.get(reverse("records:list"), {"kind": KIND})
        self.assertContains(response, "A1")
        self.assertContains(response, "A2")
        self.assertContains(response, f'<option value="{KIND}" selected>')
        self.assertContains(response, "未分類")  # 舊紀錄沒有種類

    def test_kind_cards_panel_lists_kinds_with_registered_counts(self):
        self.record(self.staff, number="A1", kind=KIND, quantity=4)
        response = self.client.get(reverse("records:list"), {"kind": KIND})
        self.assertContains(response, f"?kind={quote(KIND)}")
        self.assertContains(response, "id=\"kind-cards\"")

    def test_edit_can_change_kind(self):
        record = self.record(self.staff, kind="")
        self.client.post(reverse("records:edit", args=[record.pk]), {"kind": KIND, "number": record.number, "date_text": "", "name": "紙箱", "quantity": "1"})
        record.refresh_from_db()
        self.assertEqual(record.kind, KIND)
