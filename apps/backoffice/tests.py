from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department, Level, PagePermission, Station, User
from apps.personnel.models import Employee

from .menu import MENU


def make_user(username, level=Level.STAFF, department=None, **extra):
    return User.objects.create_user(username, password="pw12345!", name=username, level=level, department=department, **extra)


class BackofficeTestCase(TestCase):
    def login(self, user):
        self.client.login(username=user.username, password="pw12345!")


class AccessTests(BackofficeTestCase):
    def test_admin_sees_every_page(self):
        Department.objects.create(name="現場部")
        self.login(make_user("boss", Level.ADMIN))
        self.assertContains(self.client.get(reverse("home")), "後台管理")
        for item in MENU:
            self.assertEqual(self.client.get(reverse(item.url_name)).status_code, 200, item.page_key)

    def test_staff_without_permission_gets_403(self):
        self.login(make_user("e1"))
        self.assertNotContains(self.client.get(reverse("home")), "後台管理")
        self.assertEqual(self.client.get(reverse("backoffice:dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("personnel:employee_list")).status_code, 403)

    def test_page_permission_opens_a_page(self):
        PagePermission.objects.create(page_key="manage-employees", label="人員資料", min_level=Level.LEADER)
        self.login(make_user("lead", Level.LEADER))
        self.assertEqual(self.client.get(reverse("personnel:employee_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts_manage:department_list")).status_code, 403)
        dashboard = self.client.get(reverse("backoffice:dashboard"))
        self.assertContains(dashboard, "人員資料")
        self.assertNotContains(dashboard, "部門</a>")
        # 進到某一頁也看得到左側選單，目前頁面標示為 active
        self.assertContains(self.client.get(reverse("personnel:employee_list")), 'active" href="/manage/personnel/employees/"')

    def test_page_permissions_admin_only_even_if_configured(self):
        PagePermission.objects.create(page_key="manage-page-permissions", label="頁面權限", min_level=Level.STAFF)
        self.login(make_user("mgr", Level.MANAGER))
        self.assertEqual(self.client.get(reverse("accounts_manage:page_permission_list")).status_code, 403)


class CrudTests(BackofficeTestCase):
    def setUp(self):
        self.login(make_user("boss", Level.ADMIN))

    def test_create_and_edit_employee(self):
        dept = Department.objects.create(name="現場部")
        response = self.client.post(
            reverse("personnel:employee_create"),
            {"employee_no": "P001", "name": "王小明", "department": dept.pk, "level": Level.STAFF, "phone": "0912-345678 / line: wang", "is_active": "on"},
        )
        self.assertRedirects(response, reverse("personnel:employee_list"))
        employee = Employee.objects.get(employee_no="P001")
        self.assertIsNone(employee.user)
        self.client.post(reverse("personnel:employee_edit", args=[employee.pk]), {"employee_no": "P001", "name": "王小明", "level": Level.STAFF})
        employee.refresh_from_db()
        self.assertFalse(employee.is_active)

    def test_employee_list_search_and_status(self):
        Employee.objects.create(employee_no="P001", name="王小明")
        Employee.objects.create(employee_no="P002", name="李大華", is_active=False)
        url = reverse("personnel:employee_list")
        self.assertContains(self.client.get(url, {"q": "王"}), "P001")
        self.assertNotContains(self.client.get(url, {"q": "王"}), "P002")
        self.assertNotContains(self.client.get(url), "P002")
        self.assertContains(self.client.get(url, {"status": "inactive"}), "P002")

    def test_employee_form_fields(self):
        response = self.client.get(reverse("personnel:employee_create"))
        self.assertEqual(
            list(response.context["form"].fields),
            ["employee_no", "name", "level", "department", "phone", "hire_date", "note", "is_active"],
        )

    def test_delete_protected_department_shows_error(self):
        dept = Department.objects.create(name="現場部")
        Employee.objects.create(employee_no="P001", name="王小明", department=dept)
        response = self.client.post(reverse("accounts_manage:department_delete", args=[dept.pk]), follow=True)
        self.assertContains(response, "不能刪除")
        self.assertTrue(Department.objects.filter(pk=dept.pk).exists())

    def test_station_is_independent_of_department(self):
        self.client.post(reverse("accounts_manage:station_create"), {"name": "撿貨"})
        self.assertEqual(Station.objects.get().name, "撿貨")
        response = self.client.post(reverse("accounts_manage:station_create"), {"name": "撿貨"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Station.objects.count(), 1)

    def test_level_page_lists_levels_with_headcount(self):
        Employee.objects.create(employee_no="P001", name="王小明", level=Level.LEADER)
        Employee.objects.create(employee_no="P002", name="李大華", level=Level.LEADER)
        Employee.objects.create(employee_no="P003", name="離職", level=Level.LEADER, is_active=False)
        rows = self.client.get(reverse("accounts_manage:level_list")).context["rows"]
        self.assertEqual([row["cells"][0] for row in rows], ["管理員", "經理", "主任", "組長", "員工"])
        self.assertEqual(rows[3]["cells"][1], 2)

    def test_deactivating_employee_disables_account(self):
        account = make_user("E100")
        employee = Employee.objects.create(employee_no="E100", name="新人", user=account)
        self.client.post(reverse("personnel:employee_edit", args=[employee.pk]), {"employee_no": "E100", "name": "新人", "level": Level.STAFF})
        account.refresh_from_db()
        self.assertFalse(account.is_active)
        # 復職不會自動啟用帳號
        self.client.post(
            reverse("personnel:employee_edit", args=[employee.pk]), {"employee_no": "E100", "name": "新人", "level": Level.STAFF, "is_active": "on"}
        )
        account.refresh_from_db()
        self.assertFalse(account.is_active)

    def test_deactivating_admin_employee_keeps_account(self):
        account = make_user("E100", Level.ADMIN)
        employee = Employee.objects.create(employee_no="E100", name="老闆", user=account)
        employee.is_active = False
        employee.save()
        account.refresh_from_db()
        self.assertTrue(account.is_active)

    def test_open_account_button_preselects_employee(self):
        employee = Employee.objects.create(employee_no="E100", name="新人")
        Employee.objects.create(employee_no="E200", name="離職", is_active=False)
        response = self.client.get(reverse("personnel:employee_list"), {"status": "all"})
        url = f"{reverse('accounts_manage:user_create')}?employee={employee.pk}"
        self.assertContains(response, url)
        self.assertContains(response, "開帳號", count=1)
        self.assertEqual(self.client.get(url).context["form"]["employee"].value(), str(employee.pk))

    def test_create_user_requires_employee_and_copies_its_data(self):
        dept = Department.objects.create(name="現場部")
        employee = Employee.objects.create(employee_no="E100", name="新人", phone="0912", department=dept, level=Level.LEADER)
        url = reverse("accounts_manage:user_create")
        passwords = {"password1": "Wh-pass-2026", "password2": "Wh-pass-2026"}
        # 沒選人員、或憑空輸入工號都不能建立帳號
        self.client.post(url, {"username": "X1", "name": "憑空", "level": Level.STAFF, **passwords})
        self.assertFalse(User.objects.filter(username="X1").exists())
        response = self.client.post(url, {"employee": employee.pk, "is_active": "on", **passwords})
        self.assertRedirects(response, reverse("accounts_manage:user_list"))
        user = User.objects.get(username="E100")
        self.assertEqual((user.name, user.phone, user.department, user.level), ("新人", "0912", dept, Level.LEADER))
        self.assertTrue(user.check_password("Wh-pass-2026"))
        employee.refresh_from_db()
        self.assertEqual(employee.user, user)
        # 已有帳號的人員不能再建第二個帳號
        response = self.client.get(url)
        self.assertNotIn(employee, response.context["form"].fields["employee"].queryset)
        self.client.post(
            reverse("accounts_manage:user_password", args=[user.pk]),
            {"new_password1": "Another-pass-99", "new_password2": "Another-pass-99"},
        )
        user.refresh_from_db()
        self.assertTrue(user.check_password("Another-pass-99"))

    def test_employee_changes_sync_to_account_and_account_form_locks_them(self):
        account = make_user("E100")
        employee = Employee.objects.create(employee_no="E100", name="新人", user=account)
        self.client.post(
            reverse("personnel:employee_edit", args=[employee.pk]),
            {"employee_no": "E100", "name": "改名", "level": Level.DIRECTOR, "is_active": "on"},
        )
        account.refresh_from_db()
        self.assertEqual((account.name, account.level), ("改名", Level.DIRECTOR))
        response = self.client.get(reverse("accounts_manage:user_edit", args=[account.pk]))
        form = response.context["form"]
        self.assertTrue(all(form.fields[f].disabled for f in ("username", "name", "phone", "department")))
        # 管理員只能在人員資料的職級和管理員之間切換
        self.assertEqual([value for value, _ in form.fields["level"].choices], [Level.DIRECTOR, Level.ADMIN])

    def test_admin_account_level_not_overwritten_by_employee(self):
        account = make_user("E100", Level.ADMIN)
        employee = Employee.objects.create(employee_no="E100", name="新人", level=Level.MANAGER, user=account)
        employee.level = Level.LEADER
        employee.save()
        account.refresh_from_db()
        self.assertEqual(account.level, Level.ADMIN)

    def test_non_admin_limited_to_lower_levels(self):
        director = make_user("D1", Level.DIRECTOR)
        Employee.objects.create(employee_no="D1", name="主任", level=Level.DIRECTOR, user=director)
        PagePermission.objects.create(page_key="manage-employees", label="人員資料", min_level=Level.LEADER)
        PagePermission.objects.create(page_key="manage-users", label="系統帳號", min_level=Level.LEADER)
        leader = Employee.objects.create(employee_no="L1", name="組長", level=Level.LEADER)
        manager = Employee.objects.create(employee_no="M1", name="經理", level=Level.MANAGER)
        self.login(director)
        # 人員資料：只能設比自己低的職級，不能升自己
        form = self.client.get(reverse("personnel:employee_create")).context["form"]
        self.assertEqual([value for value, _ in form.fields["level"].choices], [Level.STAFF, Level.LEADER])
        self.client.post(
            reverse("personnel:employee_edit", args=[leader.pk]), {"employee_no": "L1", "name": "組長", "level": Level.MANAGER, "is_active": "on"}
        )
        leader.refresh_from_db()
        self.assertEqual(leader.level, Level.LEADER)
        own = Employee.objects.get(employee_no="D1")
        self.assertTrue(self.client.get(reverse("personnel:employee_edit", args=[own.pk])).context["form"].fields["level"].disabled)
        # 開帳號：只列出職級比自己低的人員
        queryset = self.client.get(reverse("accounts_manage:user_create")).context["form"].fields["employee"].queryset
        self.assertIn(leader, queryset)
        self.assertNotIn(manager, queryset)

    def test_inactive_employees_not_offered_for_new_account(self):
        Employee.objects.create(employee_no="E200", name="離職", is_active=False)
        response = self.client.get(reverse("accounts_manage:user_create"))
        self.assertEqual(response.context["form"].fields["employee"].queryset.count(), 0)

    def test_attendance_is_a_feature_not_in_backoffice(self):
        dashboard = self.client.get(reverse("backoffice:dashboard"))
        self.assertNotContains(dashboard, "list-group-item-action\" href=\"/attendance/")
        self.assertNotContains(dashboard, 'card-header">到班')
        self.assertContains(self.client.get(reverse("home")), 'href="/attendance/"')

    def test_page_permission_list_shows_unconfigured_pages(self):
        PagePermission.objects.create(page_key="manage-employees", label="人員資料", min_level=Level.LEADER)
        rows = self.client.get(reverse("accounts_manage:page_permission_list")).context["rows"]
        by_label = {row["cells"][1]: row for row in rows}
        self.assertEqual(by_label["人員資料"]["cells"][2], "組長以上")
        self.assertEqual(by_label["部門"]["cells"][2], "未開放（只有管理員）")
        self.assertNotIn("頁面權限", by_label)
        form = self.client.get(reverse("accounts_manage:page_permission_create"), {"page": "manage-departments"}).context["form"]
        self.assertEqual(form["page_key"].value(), "manage-departments")
        self.assertNotIn(Level.ADMIN, [value for value, _ in form.fields["min_level"].choices])

    def test_page_permission_create_uses_menu_label(self):
        response = self.client.post(
            reverse("accounts_manage:page_permission_create"), {"page_key": "manage-employees", "min_level": Level.LEADER}
        )
        self.assertRedirects(response, reverse("accounts_manage:page_permission_list"))
        self.assertEqual(PagePermission.objects.get().label, "人員資料")
        form = self.client.get(reverse("accounts_manage:page_permission_create")).context["form"]
        keys = [key for key, _ in form.fields["page_key"].choices]
        self.assertNotIn("manage-employees", keys)
        self.assertNotIn("manage-page-permissions", keys)


class UserLevelLimitTests(BackofficeTestCase):
    def setUp(self):
        PagePermission.objects.create(page_key="manage-users", label="系統帳號", min_level=Level.DIRECTOR)
        self.director = make_user("dir", Level.DIRECTOR)
        self.login(self.director)

    def test_only_lower_level_users_listed_and_editable(self):
        leader = make_user("lead", Level.LEADER)
        manager = make_user("mgr", Level.MANAGER)
        response = self.client.get(reverse("accounts_manage:user_list"))
        self.assertContains(response, "lead")
        self.assertNotContains(response, "mgr")
        self.assertEqual(self.client.get(reverse("accounts_manage:user_edit", args=[manager.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("accounts_manage:user_edit", args=[self.director.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("accounts_manage:user_password", args=[manager.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("accounts_manage:user_edit", args=[leader.pk])).status_code, 200)

    def test_cannot_promote_to_own_level(self):
        leader = make_user("lead", Level.LEADER)
        response = self.client.post(
            reverse("accounts_manage:user_edit", args=[leader.pk]),
            {"username": "lead", "name": "lead", "level": Level.DIRECTOR, "is_active": "on"},
        )
        self.assertEqual(response.status_code, 200)
        leader.refresh_from_db()
        self.assertEqual(leader.level, Level.LEADER)
