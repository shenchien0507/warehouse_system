from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import Department, Station, User

from .models import Employee


class SeedPersonnelTests(TestCase):
    def test_creates_15_employees_with_basic_fields_only(self):
        call_command("seed_personnel", stdout=StringIO())
        employees = Employee.objects.filter(employee_no__startswith="T")
        self.assertEqual(employees.count(), 15)
        for e in employees:
            self.assertTrue(e.name)
            self.assertTrue(len(e.phone) == 10 and e.phone.startswith("09"))
            self.assertIsNotNone(e.hire_date)
            self.assertIsNone(e.department_id)
        self.assertFalse(Department.objects.exists())
        self.assertFalse(Station.objects.exists())
        self.assertFalse(User.objects.exists())

    def test_rerun_does_not_duplicate(self):
        call_command("seed_personnel", stdout=StringIO())
        call_command("seed_personnel", stdout=StringIO())
        self.assertEqual(Employee.objects.count(), 15)

    def test_count_option(self):
        call_command("seed_personnel", "--count", "3", stdout=StringIO())
        self.assertEqual(Employee.objects.count(), 3)
