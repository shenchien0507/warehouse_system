from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.backoffice.views import PageMixin

from .models import PagePermission, User
from .permissions import can_access
from .testing import Level, make_user



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
        self.assertTrue(user.is_admin)


class PagePermissionTests(TestCase):
    def setUp(self):
        self.page = PagePermission.objects.create(page_key="orders", label="訂單整理", min_level=Level.LEADER)

    def test_min_level_decides_access(self):
        self.assertTrue(can_access(make_user("a", Level.LEADER), "orders"))
        self.assertTrue(can_access(make_user("b", Level.MANAGER), "orders"))
        self.assertFalse(can_access(make_user("c", Level.STAFF), "orders"))

    def test_admin_can_access_everything_even_unconfigured(self):
        self.assertTrue(can_access(make_user("boss", Level.ADMIN), "orders"))
        self.assertTrue(can_access(make_user("boss2", Level.ADMIN), "no-such-page"))

    def test_unconfigured_page_denied_for_others(self):
        self.assertFalse(can_access(make_user("a", Level.MANAGER), "no-such-page"))

    def test_inactive_user_denied(self):
        self.assertFalse(can_access(make_user("a", Level.MANAGER, is_active=False), "orders"))

    def test_page_mixin_raises_403(self):
        request = RequestFactory().get("/")
        request.user = make_user("c", Level.STAFF)

        class V(PageMixin):
            page_key = "order-stats"

        with self.assertRaises(PermissionDenied):
            V().dispatch(request)

    def test_home_lists_only_accessible_pages(self):
        PagePermission.objects.create(page_key="data-tower", label="數據塔", min_level=Level.STAFF)
        PagePermission.objects.create(page_key="records", label="登記紀錄", min_level=Level.LEADER)
        make_user("c", Level.STAFF)
        self.client.login(username="c", password="pw12345!")
        content = self.client.get(reverse("home")).content.decode()
        self.assertIn(f'href="{reverse("tower:index")}"', content)
        self.assertNotIn(f'href="{reverse("records:list")}"', content)


class UserPasswordTests(TestCase):
    def test_admin_resets_password(self):
        admin = User.objects.create_superuser("root", password="pw12345!", name="root")
        target = make_user("E001")
        self.client.force_login(admin)
        url = reverse("accounts_manage:user_password", args=[target.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {"new_password1": "Newpass123!", "new_password2": "Newpass123!"})
        self.assertRedirects(response, reverse("accounts_manage:user_edit", args=[target.pk]))
        target.refresh_from_db()
        self.assertTrue(target.check_password("Newpass123!"))
