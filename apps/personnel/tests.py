from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import Department, Station, User

from .models import Employee, JobTitle


class SeedPersonnelTests(TestCase):
    def test_creates_15_employees_with_departments_and_job_titles(self):
        call_command("seed_personnel", stdout=StringIO())
        employees = Employee.objects.filter(employee_no__startswith="T")
        self.assertEqual(employees.count(), 15)
        self.assertFalse(employees.filter(department=None).exists())
        self.assertFalse(employees.filter(job_title=None).exists())
        self.assertTrue(all(len(e.phone) == 10 and e.phone.startswith("09") for e in employees))
        self.assertTrue(Station.objects.exists())
        self.assertFalse(User.objects.exists())

    def test_rerun_does_not_duplicate(self):
        call_command("seed_personnel", stdout=StringIO())
        counts = (Employee.objects.count(), Department.objects.count(), JobTitle.objects.count(), Station.objects.count())
        call_command("seed_personnel", stdout=StringIO())
        self.assertEqual(
            (Employee.objects.count(), Department.objects.count(), JobTitle.objects.count(), Station.objects.count()), counts
        )

    def test_reuses_existing_department(self):
        dept = Department.objects.create(name="現場部")
        call_command("seed_personnel", "--count", "3", stdout=StringIO())
        self.assertEqual(Department.objects.filter(name="現場部").count(), 1)
        self.assertEqual(Employee.objects.count(), 3)
        self.assertTrue(Station.objects.filter(department=dept).exists())
