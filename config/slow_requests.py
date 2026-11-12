"""開發時（DEBUG）記錄慢的請求：超過 1 秒的在執行 runserver 的視窗印一行，看是資料庫還是其他地方慢。"""

import time

from django.conf import settings
from django.db import connection

SLOW_SECONDS = 1.0


class SlowRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.DEBUG:
            return self.get_response(request)
        start, queries = time.perf_counter(), len(connection.queries)
        response = self.get_response(request)
        spent = time.perf_counter() - start
        if spent >= SLOW_SECONDS:
            ran = connection.queries[queries:]
            db = sum(float(q["time"]) for q in ran)
            print(f"[慢] {request.method} {request.path} 共 {spent:.2f} 秒；資料庫 {len(ran)} 次查詢 {db:.2f} 秒，其他 {spent - db:.2f} 秒")
        return response
