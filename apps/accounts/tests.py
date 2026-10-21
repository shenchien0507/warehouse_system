from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .models import Department, Level, PagePermission, User
from .permissions import PageAccessMixin, can_access, page_access_required


def make_user(username, level=Level.STAFF, department=None, **extra):
    return User.objects.create_user(username, password="pw12345!", name=username, level=level, department=department, **extra)


class LoginTests(TestCase):
    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, f"{reverse('login')}?next=/")

    def test_login_with_employee_id(self):
        make_user("E001")
        response = self.client.post(reverse("login"), {"username": "E001", "password": "pw12345!"})
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_wrong_password_rejected(self):
        make_user("E001")
        response = self.client.post(reverse("login"), {"username": "E001", "password": "bad"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_cannot_login(self):
        make_user("E002", is_active=False)
        self.client.post(reverse("login"), {"username": "E002", "password": "pw12345!"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self):
        make_user("E001")
        self.client.login(username="E001", password="pw12345!")
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))

    def test_superuser_is_admin_level(self):
        user = User.objects.create_superuser("root", password="pw12345!", name="root")
        self.assertEqual(user.level, Level.ADMIN)


class PagePermissionTests(TestCase):
    def setUp(self):
        self.orders = Department.objects.create(name="訂單部")
        self.punch = Department.objects.create(name="現場部")
        self.page = PagePermission.objects.create(page_key="orders", label="訂單整理", min_level=Level.LEADER)
        self.page.departments.add(self.orders)

    def test_level_and_department_must_both_match(self):
        self.assertTrue(can_access(make_user("a", Level.LEADER, self.orders), "orders"))
        self.assertTrue(can_access(make_user("b", Level.MANAGER, self.orders), "orders"))
        self.assertFalse(can_access(make_user("c", Level.STAFF, self.orders), "orders"))
        self.assertFalse(can_access(make_user("d", Level.MANAGER, self.punch), "orders"))
        self.assertFalse(can_access(make_user("e", Level.MANAGER), "orders"))

    def test_no_departments_means_all_departments(self):
        self.page.departments.clear()
        self.assertTrue(can_access(make_user("a", Level.LEADER, self.punch), "orders"))

    def test_admin_can_access_everything_even_unconfigured(self):
        self.assertTrue(can_access(make_user("boss", Level.ADMIN), "orders"))
        self.assertTrue(can_access(make_user("boss2", Level.ADMIN), "no-such-page"))

    def test_unconfigured_page_denied_for_others(self):
        self.assertFalse(can_access(make_user("a", Level.MANAGER, self.orders), "no-such-page"))

    def test_inactive_user_denied(self):
        self.assertFalse(can_access(make_user("a", Level.MANAGER, self.orders, is_active=False), "orders"))

    def test_decorator_and_mixin_raise_403(self):
        request = RequestFactory().get("/")
        request.user = make_user("c", Level.STAFF, self.orders)

        @page_access_required("orders")
        def view(request):
            return "ok"

        with self.assertRaises(PermissionDenied):
            view(request)

        class V(PageAccessMixin):
            page_key = "orders"

        with self.assertRaises(PermissionDenied):
            V().dispatch(request)

    def test_home_lists_only_accessible_pages(self):
        PagePermission.objects.create(page_key="punch", label="上下班打卡")
        make_user("c", Level.STAFF, self.orders)
        self.client.login(username="c", password="pw12345!")
        content = self.client.get(reverse("home")).content.decode()
        self.assertIn("上下班打卡", content)
        self.assertNotIn("訂單整理", content)
