"""當日統計的計算結果暫存在記憶體，同樣的資料不用每次開頁面都重算
（當日統計、數據塔每分鐘自動更新，登記紀錄頁的種類卡也要用到當日的數字）。
key 裡帶著資料的指紋（批次、各批的商品列數、抽單狀態），資料有變就是新的 key，自動重算；
每個伺服器程序各自暫存，最多 settings.DAILY_STATS_CACHE_SIZE 筆，0 代表不暫存（跑測試時）。"""

import threading
from collections import OrderedDict

from django.conf import settings

_entries = OrderedDict()
_lock = threading.Lock()


def remember(key, compute):
    """有暫存就回傳暫存的結果，沒有就呼叫 compute() 算一次存起來。"""
    size = getattr(settings, "DAILY_STATS_CACHE_SIZE", 0)
    if not size:
        return compute()
    with _lock:
        if key in _entries:
            _entries.move_to_end(key)
            return _entries[key]
    value = compute()
    with _lock:
        _entries[key] = value
        _entries.move_to_end(key)
        while len(_entries) > size:
            _entries.popitem(last=False)
    return value


def clear():
    with _lock:
        _entries.clear()
