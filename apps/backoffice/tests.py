from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department, Level, PagePermission, Station, User
from apps.personnel.models import Employee, JobTitle

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

    def test_page_permissions_admin_only_even_if_configured(self):
        PagePermission.objects.create(page_key="manage-page-permissions", label="頁面權限", min_level=Level.STAFF)
        self.login(make_user("mgr", Level.MANAGER))
        self.assertEqual(self.client.get(reverse("accounts_manage:page_permission_list")).status_code, 403)


class CrudTests(BackofficeTestCase):
    def setUp(self):
        self.login(make_user("boss", Level.ADMIN))

    def test_create_and_edit_employee(self):
        dept = Department.objects.create(name="現場部")
        job = JobTitle.objects.create(name="倉管")
        response = self.client.post(
            reverse("personnel:employee_create"),
            {"employee_no": "P001", "name": "王小明", "department": dept.pk, "job_title": job.pk, "is_active": "on"},
        )
        self.assertRedirects(response, reverse("personnel:employee_list"))
        employee = Employee.objects.get(employee_no="P001")
        self.assertIsNone(employee.user)
        self.client.post(reverse("personnel:employee_edit", args=[employee.pk]), {"employee_no": "P001", "name": "王小明"})
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

    def test_employee_form_has_no_account_field(self):
        response = self.client.get(reverse("personnel:employee_create"))
        self.assertNotIn("user", response.context["form"].fields)

    def test_delete_protected_department_shows_error(self):
        dept = Department.objects.create(name="現場部")
        Station.objects.create(name="撿貨", department=dept)
        response = self.client.post(reverse("accounts_manage:department_delete", args=[dept.pk]), follow=True)
        self.assertContains(response, "不能刪除")
        self.assertTrue(Department.objects.filter(pk=dept.pk).exists())

    def test_delete_unused_job_title(self):
        job = JobTitle.objects.create(name="倉管")
        self.client.post(reverse("personnel:job_title_delete", args=[job.pk]))
        self.assertFalse(JobTitle.objects.exists())

    def test_create_user_requires_employee_and_copies_its_data(self):
        dept = Department.objects.create(name="現場部")
        employee = Employee.objects.create(employee_no="E100", name="新人", phone="0912", department=dept)
        url = reverse("accounts_manage:user_create")
        passwords = {"password1": "Wh-pass-2026", "password2": "Wh-pass-2026"}
        # 沒選人員、或憑空輸入工號都不能建立帳號
        self.client.post(url, {"username": "X1", "name": "憑空", "level": Level.STAFF, **passwords})
        self.assertFalse(User.objects.filter(username="X1").exists())
        response = self.client.post(url, {"employee": employee.pk, "level": Level.STAFF, "is_active": "on", **passwords})
        self.assertRedirects(response, reverse("accounts_manage:user_list"))
        user = User.objects.get(username="E100")
        self.assertEqual((user.name, user.phone, user.department), ("新人", "0912", dept))
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
        self.client.post(reverse("personnel:employee_edit", args=[employee.pk]), {"employee_no": "E100", "name": "改名", "is_active": "on"})
        account.refresh_from_db()
        self.assertEqual(account.name, "改名")
        response = self.client.get(reverse("accounts_manage:user_edit", args=[account.pk]))
        form = response.context["form"]
        self.assertTrue(all(form.fields[f].disabled for f in ("username", "name", "phone", "department")))

    def test_inactive_employees_not_offered_for_new_account(self):
        Employee.objects.create(employee_no="E200", name="離職", is_active=False)
        response = self.client.get(reverse("accounts_manage:user_create"))
        self.assertEqual(response.context["form"].fields["employee"].queryset.count(), 0)

    def test_attendance_is_a_feature_not_in_backoffice(self):
        dashboard = self.client.get(reverse("backoffice:dashboard"))
        self.assertNotContains(dashboard, "list-group-item-action\" href=\"/attendance/")
        self.assertNotContains(dashboard, 'card-header">到班')
        self.assertContains(self.client.get(reverse("home")), 'href="/attendance/"')

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
