import datetime
import random

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Department, Station
from apps.personnel.models import Employee, JobTitle

# 部門 → 該部門的工位與可能職務
STRUCTURE = {
    "現場部": {"stations": ["收貨", "上架", "撿貨", "包裝", "出貨"], "job_titles": ["倉管", "撿貨員", "包裝員", "堆高機司機"]},
    "物流部": {"stations": ["理貨", "裝車"], "job_titles": ["理貨員", "司機"]},
    "辦公室": {"stations": ["行政"], "job_titles": ["行政助理", "倉儲專員"]},
}
SURNAMES = "陳林黃張李王吳劉蔡楊許鄭謝洪郭邱曾廖賴徐周葉蘇莊呂江何蕭羅高"
GIVEN_CHARS = "家宜建志明俊雅婷怡君冠宇承翰佳穎欣怡宗翰柏宏淑芬美玲文傑嘉豪子涵詩涵"


def random_name(rng):
    return rng.choice(SURNAMES) + "".join(rng.choice(GIVEN_CHARS) for _ in range(2))


def random_phone(rng):
    return "09" + "".join(str(rng.randint(0, 9)) for _ in range(8))


class Command(BaseCommand):
    help = "產生本機測試用的假人員資料（工號 T001 起），缺少的部門、職務、工位會一併建立。重複執行不會重複建立。"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=15, help="人數，預設 15")
        parser.add_argument("--seed", type=int, help="亂數種子，指定後每次產生相同資料")

    @transaction.atomic
    def handle(self, *args, count, seed, **options):
        rng = random.Random(seed)
        departments = {}
        for dept_name, spec in STRUCTURE.items():
            dept, _ = Department.objects.get_or_create(name=dept_name)
            for station_name in spec["stations"]:
                Station.objects.get_or_create(department=dept, name=station_name)
            departments[dept] = [JobTitle.objects.get_or_create(name=name)[0] for name in spec["job_titles"]]

        # 現場部人多，其他部門少一點
        weights = [6 if dept.name == "現場部" else 2 for dept in departments]
        today = timezone.localdate()
        created = skipped = 0
        for i in range(1, count + 1):
            dept = rng.choices(list(departments), weights=weights)[0]
            employee, is_new = Employee.objects.get_or_create(
                employee_no=f"T{i:03d}",
                defaults={
                    "name": random_name(rng),
                    "department": dept,
                    "job_title": rng.choice(departments[dept]),
                    "phone": random_phone(rng),
                    "hire_date": today - datetime.timedelta(days=rng.randint(30, 365 * 5)),
                    "note": "測試資料（seed_personnel 產生）",
                },
            )
            if is_new:
                created += 1
            else:
                skipped += 1
        self.stdout.write(self.style.SUCCESS(f"新增 {created} 位人員，已存在略過 {skipped} 位。"))
