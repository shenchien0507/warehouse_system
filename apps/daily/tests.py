from datetime import date, datetime, time, timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import PagePermission
from apps.accounts.testing import Level, make_user
from apps.orders.tests import xlsx

from .models import DailyBatch, DailyHold, DailyLine, DailyOrder

HEADERS = ["交易平台", "交易序號", "出貨類型", "商品編號", "建立時間"]
MORNING = [
    ["蝦皮購物", 1, "蝦皮無包裝", "A", "2026/10/05 09:00:00"],
    ["蝦皮購物", 1, "蝦皮無包裝", "B", "2026/10/05 09:00:00"],
    ["蝦皮購物", 2, "蝦皮隔日到貨", "A", "2026/10/04 20:00:00"],
    ["friDay商城", 3, "7-11", "A", "2026/10/05 00:00:00"],
]
AFTERNOON = [
    ["蝦皮購物", 2, "蝦皮隔日到貨", "A", "2026/10/04 20:00:00"],  # 上午已經有了
    ["蝦皮購物", 4, "蝦皮隔日到貨", "A", "2026/10/05 15:00:00"],
    ["friDay商城", 5, "7-11", "A", "2026/10/05 00:00:00"],
]
WORK_DATE = date(2026, 10, 5)


class DailyStatsTests(TestCase):
    def setUp(self):
        self.client.login(username=make_user("boss", Level.ADMIN).username, password="pw12345!")

    def upload(self, rows, clock="10:00", work_date="2026-10-05", name=None):
        """匯入一律算進今天：把系統時間設成 work_date 那天的 clock。"""
        hour, minute = map(int, clock.split(":"))
        now = timezone.make_aware(datetime.combine(date.fromisoformat(work_date), time(hour, minute)))
        with mock.patch("django.utils.timezone.now", return_value=now):
            return self.client.post(reverse("daily:day_list"), {"file": xlsx(HEADERS, rows, name=name or f"{clock}.xlsx")})

    def today_page(self, today=WORK_DATE):
        """沒指定日期的當日統計頁：一律看今天（系統日期）。"""
        with mock.patch("django.utils.timezone.now", return_value=timezone.make_aware(datetime.combine(today, time(16, 0)))):
            return self.client.get(reverse("daily:day_list"))

    def day(self):
        return self.client.get(reverse("daily:day_detail", args=[WORK_DATE]))

    def table(self, summary):
        return {(r.name, r.period): r.count.distinct for r in summary.groups}

    def test_batches_accumulate_and_duplicates_count_once_in_first_batch(self):
        response = self.upload(MORNING, "10:00")
        self.assertRedirects(response, reverse("daily:day_detail", args=[WORK_DATE]))
        self.upload(AFTERNOON, "15:00")
        first, second = DailyBatch.objects.order_by("seq")
        self.assertEqual((first.seq, first.order_count, first.new_order_count), (1, 3, 3))
        self.assertEqual((second.seq, second.order_count, second.new_order_count, second.duplicate_order_count), (2, 3, 2, 1))
        self.assertEqual(DailyOrder.objects.count(), 5)
        self.assertEqual(DailyOrder.objects.get(order_no="2").batch, first)
        duplicate = DailyLine.objects.get(batch=second, order_no="2")
        self.assertTrue(duplicate.is_duplicate)
        self.assertEqual(DailyLine.objects.count(), 7)  # 重複的列照存

        response = self.day()
        self.assertEqual(response.context["board"].total, 5)
        self.assertEqual(response.context["duplicates"], [("2", "第 1 批", [2])])
        # 00:00:00 的訂單用各自那批的匯入時間：3 號 10:00 → 前，5 號 15:00 → 後
        self.assertEqual(
            self.table(response.context["total"]["summary"]),
            {("蝦皮無包裝", "14:00 前"): 1, ("蝦皮隔日到貨", "14:00 前"): 1, ("蝦皮隔日到貨", "14:00 後"): 1,
             ("其他平台", "14:00 前"): 1, ("其他平台", "14:00 後"): 1},
        )
        sections = response.context["sections"]
        self.assertEqual(self.table(sections[1]["summary"]), {("蝦皮隔日到貨", "14:00 後"): 1, ("其他平台", "14:00 後"): 1})
        self.assertContains(response, "重複出現在")

    def test_dashboard_numbers_and_partial_refresh(self):
        self.upload(MORNING, "10:00")
        self.upload(AFTERNOON, "15:00")
        response = self.today_page()  # 沒指定日期：今天
        board = response.context["board"]
        self.assertEqual(board.total, 5)
        self.assertEqual(
            [(c.name, c.total, c.counts, c.cutoff) for c in board.groups],
            [
                ("蝦皮無包裝", 1, {"before": 1}, "14:00"),
                ("蝦皮隔日到貨", 2, {"before": 1, "after": 1}, "14:00"),  # 蝦皮其他沒有訂單，不列
                ("其他平台", 2, {"before": 1, "after": 1}, "14:00"),
            ],
        )
        no_box = board.groups[0]  # 蝦皮無包裝列非去重：1 號訂單 2 列，卡片主要顯示非去重
        self.assertEqual((no_box.main, no_box.shown, no_box.total), (2, {"before": 2}, 1))
        self.assertEqual(board.groups[1].main, 2)  # 沒列非去重的照去重
        self.assertEqual([(b.seq, earlier, added) for b, earlier, added, *_ in board.batches], [(1, 0, 3), (2, 3, 2)])
        self.assertContains(response, 'id="daily-dashboard"')
        partial = self.client.get(reverse("daily:day_list"), {"partial": 1})
        self.assertContains(partial, "作業日 2026/10/05")
        self.assertNotContains(partial, 'id="daily-import"')

    def test_same_file_again_is_rejected(self):
        self.upload(MORNING, "10:00")
        response = self.upload(MORNING, "11:00", name="改了檔名.xlsx")
        self.assertContains(response, "內容一樣，已經匯入過")
        self.assertEqual(DailyBatch.objects.count(), 1)
        self.assertEqual(DailyLine.objects.count(), 4)

    def test_file_with_only_known_orders_is_rejected(self):
        self.upload(MORNING, "10:00")
        response = self.upload(MORNING[:2], "11:00")  # 內容不同，但訂單都匯過了
        self.assertContains(response, "全部都已在之前的批次匯入過")
        self.assertEqual(DailyBatch.objects.count(), 1)

    def test_same_file_on_another_work_date_is_rejected(self):
        self.upload(MORNING)
        response = self.upload(MORNING, work_date="2026-10-06")
        self.assertContains(response, "內容一樣，已經匯入過")
        self.assertFalse(DailyBatch.objects.filter(work_date=date(2026, 10, 6)).exists())

    def test_orders_from_another_work_date_count_once_on_first_day(self):
        self.upload(MORNING, "10:00")  # 10/05：1、2、3
        self.upload(AFTERNOON, "15:00", work_date="2026-10-06")  # 10/06：2 重複，4、5 新的
        batch = DailyBatch.objects.get(work_date=date(2026, 10, 6))
        self.assertEqual((batch.order_count, batch.new_order_count), (3, 2))
        self.assertEqual(DailyOrder.objects.count(), 5)
        self.assertEqual(DailyOrder.objects.get(order_no="2").work_date, WORK_DATE)
        response = self.client.get(reverse("daily:day_detail", args=[date(2026, 10, 6)]))
        self.assertEqual(response.context["board"].total, 2)
        self.assertEqual(response.context["duplicates"], [("2", "10/05 第 1 批", [1])])
        # 10/05 那批的訂單已在 10/06 重複出現，不能刪
        first = DailyBatch.objects.get(work_date=WORK_DATE)
        self.client.post(reverse("daily:batch_delete", args=[first.pk]))
        self.assertTrue(DailyBatch.objects.filter(pk=first.pk).exists())
        self.client.post(reverse("daily:batch_delete", args=[batch.pk]))
        self.client.post(reverse("daily:batch_delete", args=[first.pk]))
        self.assertFalse(DailyBatch.objects.exists())

    def test_bad_file_not_imported(self):
        response = self.upload([["蝦皮購物", "", "宅配", "A", "2026/10/05 09:00:00"]])
        self.assertContains(response, "訂單號空白")
        self.assertFalse(DailyBatch.objects.exists())

    def test_deleting_missing_batch_redirects_with_message(self):
        # 連按兩下刪除：第二次送出時這批已經不在了，不要顯示 404
        self.upload(MORNING, "10:00")
        batch = DailyBatch.objects.get()
        self.client.post(reverse("daily:batch_delete", args=[batch.pk]))
        response = self.client.post(reverse("daily:batch_delete", args=[batch.pk]), follow=True)
        self.assertRedirects(response, reverse("daily:day_list"))
        self.assertContains(response, "這批已經刪除了")

    def test_only_latest_batch_can_be_deleted(self):
        self.upload(MORNING, "10:00")
        self.upload(AFTERNOON, "15:00")
        first, second = DailyBatch.objects.order_by("seq")
        self.client.post(reverse("daily:batch_delete", args=[first.pk]))
        self.assertEqual(DailyBatch.objects.count(), 2)
        self.client.post(reverse("daily:batch_delete", args=[second.pk]))
        self.assertEqual(list(DailyBatch.objects.all()), [first])
        self.assertEqual(DailyOrder.objects.count(), 3)
        self.assertFalse(DailyLine.objects.filter(is_duplicate=True).exists())
        self.upload(AFTERNOON, "16:00")
        self.assertEqual(DailyBatch.objects.order_by("seq").last().seq, 2)

    def hold(self, order_no, reason="缺貨", work_date=WORK_DATE):
        order = DailyOrder.objects.get(order_no=order_no, work_date=work_date)
        return self.client.post(reverse("daily:hold", args=[order.pk]), {"reason": reason, "q": order_no})

    def cards(self, work_date=WORK_DATE):
        board = self.client.get(reverse("daily:day_detail", args=[work_date])).context["board"]
        return board.total, board.held, {c.name: (c.main, c.held) for c in board.groups}

    def test_search_finds_order_with_group_and_period(self):
        self.upload(MORNING, "10:00")
        self.upload(AFTERNOON, "15:00")
        response = self.client.get(reverse("daily:day_detail", args=[WORK_DATE]), {"q": "2"})
        found = response.context["found"]
        self.assertEqual([o.order_no for o in found], ["2"])
        self.assertEqual(found[0].place, ("蝦皮隔日到貨", "14:00 前"))
        self.assertEqual([(line.batch.seq, line.is_duplicate) for line in found[0].found_lines], [(1, False), (2, True)])
        self.assertContains(response, "抽起原因")
        # 這天查不到，提示在哪天
        response = self.client.get(reverse("daily:day_detail", args=[WORK_DATE]), {"q": "99"})
        self.assertEqual(response.context["found"], [])

    def test_hold_and_release_change_numbers(self):
        self.upload(MORNING, "10:00")
        self.assertEqual(self.cards(), (3, 0, {"蝦皮無包裝": (2, 0), "蝦皮隔日到貨": (1, 0), "其他平台": (1, 0)}))
        response = self.hold("2")
        self.assertRedirects(response, reverse("daily:day_detail", args=[WORK_DATE]) + "?q=2#daily-search", fetch_redirect_response=False)
        # 卡片扣掉，顯示抽起；總數 0 的分組因為有抽起還是列出
        self.assertEqual(self.cards(), (2, 1, {"蝦皮無包裝": (2, 0), "蝦皮隔日到貨": (0, 1), "其他平台": (1, 0)}))
        self.hold("2")  # 已經抽起，不重複
        self.assertEqual(DailyHold.objects.count(), 1)
        self.assertEqual(self.hold("3", reason=" ").status_code, 302)  # 沒填原因不抽
        self.assertEqual(DailyHold.objects.count(), 1)
        hold = DailyHold.objects.get()
        with mock.patch("django.utils.timezone.localdate", return_value=WORK_DATE):
            self.client.post(reverse("daily:release", args=[hold.pk]))
        hold.refresh_from_db()
        self.assertEqual(hold.status, DailyHold.RELEASED)
        self.assertEqual(self.cards()[:2], (3, 0))
        self.hold("2", reason="地址有問題")  # 可以再抽一次
        self.assertEqual(DailyHold.objects.filter(order__order_no="2").count(), 2)
        self.assertContains(self.today_page(), "地址有問題")

    def test_held_order_in_later_batch_same_day_returns(self):
        self.upload(MORNING, "10:00")
        self.hold("2")
        self.upload(AFTERNOON, "15:00")  # 2 號又出現
        hold = DailyHold.objects.get()
        self.assertEqual((hold.status, hold.released_batch.seq), (DailyHold.RETURNED, 2))
        self.assertEqual(hold.outcome, "第 2 批出現，自動放回")
        self.assertEqual(self.cards()[:2], (5, 0))
        self.assertEqual(DailyOrder.objects.get(order_no="2").batch.seq, 1)  # 還是算在原本那批
        # 刪掉第 2 批：又變回抽起中
        self.client.post(reverse("daily:batch_delete", args=[hold.released_batch.pk]))
        hold.refresh_from_db()
        self.assertEqual((hold.status, hold.released_batch), (DailyHold.HELD, None))
        self.assertEqual(self.cards()[:2], (2, 1))

    def test_file_with_only_held_orders_is_accepted(self):
        self.upload(MORNING, "10:00")
        self.hold("2")
        response = self.upload(MORNING[2:3], "11:00")
        self.assertNotContains(response, "全部都已在之前的批次匯入過", status_code=302)
        self.assertEqual(DailyHold.objects.get().status, DailyHold.RETURNED)

    def test_held_order_in_another_work_date_moves_there(self):
        self.upload(MORNING, "10:00")  # 10/05：1、2、3
        self.hold("2")
        self.upload(AFTERNOON, "15:00", work_date="2026-10-06")  # 10/06：2 轉過來，4、5
        hold = DailyHold.objects.get()
        self.assertEqual(hold.status, DailyHold.MOVED)
        self.assertEqual(hold.outcome, "轉到 10/06 第 1 批")
        batch = DailyBatch.objects.get(work_date=date(2026, 10, 6))
        self.assertEqual(batch.new_order_count, 3)
        self.assertFalse(DailyLine.objects.filter(batch=batch, is_duplicate=True).exists())
        self.assertEqual(self.cards()[:2], (2, 0))  # 10/05 不算，也不再算抽起中
        self.assertEqual(self.cards(date(2026, 10, 6))[:2], (3, 0))
        # 之後再出現 2 號：算在 10/06 那筆的重複
        self.upload([AFTERNOON[0], ["蝦皮購物", 6, "宅配", "A", "2026/10/06 09:00:00"]], "16:00", work_date="2026-10-07")
        dup = DailyLine.objects.get(batch__work_date=date(2026, 10, 7), order_no="2")
        self.assertTrue(dup.is_duplicate)
        self.assertEqual(dup.order.work_date, date(2026, 10, 6))
        # 10/06 搜尋看得到；10/05 搜尋顯示已轉走
        response = self.client.get(reverse("daily:day_detail", args=[WORK_DATE]), {"q": "2"})
        self.assertContains(response, "轉到 10/06 第 1 批，這天不算")
        # 刪掉 10/07、10/06 的批次：10/05 又變回抽起中
        DailyBatch.objects.get(work_date=date(2026, 10, 7)).delete()
        self.client.post(reverse("daily:batch_delete", args=[batch.pk]))
        hold.refresh_from_db()
        self.assertEqual(hold.status, DailyHold.HELD)
        self.assertEqual(self.cards()[:2], (2, 1))

    def test_release_after_work_date_carries_to_today(self):
        self.upload(MORNING, "10:00")  # 10/05
        self.hold("1")  # 只抽了現場面單，之後的訂單檔不會再出現
        hold = DailyHold.objects.get()
        tomorrow = date(2026, 10, 6)
        with mock.patch("django.utils.timezone.localdate", return_value=tomorrow):
            response = self.client.post(reverse("daily:release", args=[hold.pk]), follow=True)
            self.assertContains(response, "今天還沒匯入")
            hold.refresh_from_db()
            self.assertEqual(hold.status, DailyHold.HELD)
            self.upload(AFTERNOON, "09:00", work_date="2026-10-06")
            response = self.client.post(reverse("daily:release", args=[hold.pk]))
            self.assertRedirects(response, reverse("daily:day_detail", args=[tomorrow]), fetch_redirect_response=False)
        hold.refresh_from_db()
        self.assertEqual((hold.status, hold.outcome), (DailyHold.CARRIED, "手動放回，轉到 10/06 第 1 批"))
        self.assertEqual(self.cards()[:2], (2, 0))  # 10/05 不算
        total, held, cards = self.cards(tomorrow)
        self.assertEqual((total, held), (3, 0))  # 10/06：4、5 加上轉過來的 1
        self.assertEqual(cards["蝦皮無包裝"], (2, 0))
        # 之後再出現 1 號：算在 10/06 那筆的重複
        self.upload([MORNING[0], ["蝦皮購物", 7, "宅配", "A", "2026/10/07 09:00:00"]], "10:00", work_date="2026-10-07")
        self.assertEqual(DailyLine.objects.get(batch__work_date=date(2026, 10, 7), order_no="1").order.work_date, tomorrow)
        # 刪掉 10/07、10/06 的批次：10/05 又變回抽起中
        DailyBatch.objects.get(work_date=date(2026, 10, 7)).delete()
        self.client.post(reverse("daily:batch_delete", args=[DailyBatch.objects.get(work_date=tomorrow).pk]))
        hold.refresh_from_db()
        self.assertEqual(hold.status, DailyHold.HELD)

    def test_page_permission(self):
        self.client.login(username=make_user("staff", Level.STAFF).username, password="pw12345!")
        self.assertEqual(self.client.get(reverse("daily:day_list")).status_code, 403)
        PagePermission.objects.create(page_key="daily-stats", label="當日統計", min_level=Level.STAFF)
        self.assertContains(self.client.get(reverse("daily:day_list")), "還沒有匯入")


class DailyRegisteredCardTests(DailyStatsTests.__bases__[0]):
    """卡片上的「已登記 / 總數」：登記紀錄裡同種類今天登記的數量對當日統計的總數。"""

    def test_card_shows_registered_over_total_and_links_to_records(self):
        from apps.records.models import Record

        today = timezone.localdate()
        client_user = make_user("boss", Level.ADMIN)
        self.client.login(username=client_user.username, password="pw12345!")
        rows = [["蝦皮購物", n, "蝦皮隔日到貨", "A", f"{today:%Y/%m/%d} 09:00:00"] for n in (1, 2, 3)]
        self.client.post(reverse("daily:day_list"), {"file": xlsx(HEADERS, rows, name="a.xlsx"), "work_date": f"{today:%Y-%m-%d}"})
        Record.objects.create(number="X1", name="x", quantity=2, kind="蝦皮隔日到貨")
        response = self.client.get(reverse("daily:day_list"))
        self.assertContains(response, "已登記 <strong>2</strong> / 3")
        self.assertContains(response, "register-short")
        self.assertContains(response, "/records/?kind=")
        Record.objects.create(number="X2", name="x", quantity=1, kind="蝦皮隔日到貨")
        self.assertContains(self.client.get(reverse("daily:day_list")), "register-even")


class DailyTodayTests(TestCase):
    """系統操作一律是今天：匯入不能選作業日，頁面不跟著最新匯入的日子跑；其他日子只能從網址查歷史。"""

    def setUp(self):
        self.client.login(username=make_user("boss", Level.ADMIN).username, password="pw12345!")

    def test_import_always_goes_to_today_and_page_shows_today(self):
        today = timezone.localdate()
        response = self.client.post(
            reverse("daily:day_list"),
            {"file": xlsx(HEADERS, MORNING, name="a.xlsx"), "work_date": "2030-01-01"},  # 送了日期也不理
        )
        self.assertRedirects(response, reverse("daily:day_detail", args=[today]))
        self.assertEqual(list(DailyBatch.objects.values_list("work_date", flat=True)), [today])
        self.assertNotContains(self.client.get(reverse("daily:day_list")), 'name="work_date"')

    def test_other_days_are_history_only(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        with mock.patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(days=1)):
            self.client.post(reverse("daily:day_list"), {"file": xlsx(HEADERS, MORNING, name="a.xlsx")})
        self.assertTrue(DailyBatch.objects.filter(work_date=tomorrow).exists())
        response = self.client.get(reverse("daily:day_list"))  # 今天還沒匯入，不會跳到明天
        self.assertContains(response, "還沒有匯入")
        self.assertNotIn("board", response.context)
        history = self.client.get(reverse("daily:day_detail", args=[tomorrow]))
        self.assertContains(history, "歷史紀錄")
        self.assertNotContains(history, 'name="file"')
