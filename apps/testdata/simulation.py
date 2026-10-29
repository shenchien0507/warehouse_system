"""訂單流模擬：模擬 ERP 一直把各平台的訂單流進「新訂單」，分批整理成「正式訂單」的操作流程。

每張單記著目前在哪個位置（新訂單、急單、出貨中、正式訂單），不會真的搬檔案：
- 時間往前推：這段時間的新單照真實的每小時曲線流進來，按比例隨機抽一小部分到急單、出貨中。
- 產生正式訂單：照 急單 → 出貨中 → 新訂單（預計出貨日越早、建立越早越先）的順序挑 N 張改成正式訂單；
  沒挑到的急單、出貨中退回新訂單，剩下的新訂單再按比例重新抽急單、出貨中。
進度存在伺服器的暫存檔（STATE_PATH），不寫進資料庫，同一時間只有一個模擬。"""

import json
import random
import zipfile
from datetime import datetime, time, timedelta
from io import BytesIO

from django.conf import settings

from .catalog import load_catalog
from .generator import TIME_FORMAT, new_order, new_shipment_no, order_rows, platform_choices, weighted, workbook_bytes

STATE_PATH = settings.BASE_DIR / ".testdata" / "simulation.json"

NEW, URGENT, SHIPPING, FORMAL = "new", "urgent", "shipping", "formal"
POOLS = [(NEW, "新訂單"), (URGENT, "急單"), (SHIPPING, "出貨中")]
POOL_LABELS = dict(POOLS)
PICK_ORDER = {URGENT: 0, SHIPPING: 1, NEW: 2}

# 歷史紀錄每小時的建立訂單數（0 點起），新單照這個曲線流進來：凌晨少、晚上 20～23 點最多
HOURLY = [3133, 1695, 1071, 681, 532, 578, 1033, 1716, 1980, 2366, 2921, 2752,
          3049, 3095, 3238, 3372, 3259, 2997, 3027, 3513, 3943, 4370, 4478, 4062]
MAX_ADVANCE = timedelta(days=7)  # 一次最多推進幾天，避免一次產生太多單

# 範例檔的出貨規律：這些單 14:00 前（含 14:00 那一分鐘）建立的當天出，之後的隔天出；其他的單都是隔天出
SAME_DAY_CUTOFF = time(14, 0, 59)
SAME_DAY_SHIP_TYPES = ("無包裝", "隔日到貨")  # 蝦皮購物
SAME_DAY_PLATFORMS = ("自訂交易", "生活市集")


def parse(value):
    return datetime.strptime(value, TIME_FORMAT)


def due_date(order):
    """預計出貨日：產生正式訂單時，新訂單照這個排先後。"""
    created = parse(order["created"])
    same_day = (
        order["platform"] in SAME_DAY_PLATFORMS
        or (order["platform"] == "蝦皮購物" and any(t in order["ship_type"] for t in SAME_DAY_SHIP_TYPES))
    )
    if created.time() != time(0) and same_day and created.time() <= SAME_DAY_CUTOFF:
        return created.date()
    return created.date() + timedelta(days=1)


def load():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def save(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def reset():
    STATE_PATH.unlink(missing_ok=True)


def start(clock, live, orders_per_day, urgent_pct, shipping_pct, options, first_order_no):
    return {
        "started": clock.strftime(TIME_FORMAT), "clock": clock.strftime(TIME_FORMAT), "live": live,
        "orders_per_day": orders_per_day, "urgent_pct": urgent_pct, "shipping_pct": shipping_pct,
        "options": options, "next_order_no": first_order_no, "orders": [], "rounds": [],
    }


def pull_status(rng, state):
    """按比例決定一張新訂單要不要被抽到急單或出貨中。"""
    r = rng.random() * 100
    if r < state["urgent_pct"]:
        return URGENT
    if r < state["urgent_pct"] + state["shipping_pct"]:
        return SHIPPING
    return NEW


def advance(state, to, rng=None):
    """時間推進到 to，期間的新單流進來；回傳流進來幾張。to 不能早於目前時間，一次最多 MAX_ADVANCE。"""
    rng = rng or random.Random()
    catalog = load_catalog()
    platforms = {p["name"]: p for p in catalog["platforms"]}
    choices = platform_choices(state["options"], platforms)
    clock = parse(state["clock"])
    to = min(to, clock + MAX_ADVANCE)
    added = 0
    total = sum(HOURLY)
    while clock < to:
        end = min(to, clock.replace(minute=0, second=0) + timedelta(hours=1))
        expected = state["orders_per_day"] * HOURLY[clock.hour] / total * (end - clock).total_seconds() / 3600
        count = int(expected) + (rng.random() < expected % 1)
        span = int((end - clock).total_seconds())
        for created in sorted(clock + timedelta(seconds=rng.randrange(max(span, 1))) for _ in range(count)):
            platform, types = weighted(rng, choices)
            order = new_order(rng, catalog, platforms[platform], types, created, state["next_order_no"])
            order.update(status=pull_status(rng, state), round=None, shipment_no="", arrived=created.strftime(TIME_FORMAT))
            state["orders"].append(order)
            state["next_order_no"] += 1
            added += 1
        clock = end
    state["clock"] = clock.strftime(TIME_FORMAT)
    return added


def pool_orders(state, status=None):
    return [o for o in state["orders"] if (o["status"] == status if status else o["status"] != FORMAL)]


def pick_key(order):
    return PICK_ORDER[order["status"]], due_date(order), order["created"], order["order_no"]


def cut_orders(state):
    """上次截斷（下載三個檔）時在池子裡的單；還沒截斷過就用目前時間。
    跟著現在時間走的模擬，看統計的時候還會有新單流進來，這些單留到下一次截斷。"""
    cut = state.get("cut") or state["clock"]
    return [o for o in pool_orders(state) if o["arrived"] <= cut]


def release(state, count, rng=None):
    """從上次截斷的單裡挑 count 張改成正式訂單（新的一輪）；回傳這一輪的紀錄。"""
    rng = rng or random.Random()
    catalog = load_catalog()
    pool = cut_orders(state)
    picked = sorted(pool, key=pick_key)[:count]
    picked_nos = {o["order_no"] for o in picked}
    round_no = len(state["rounds"]) + 1
    sources = {key: 0 for key, _ in POOLS}
    for order in picked:
        sources[order["status"]] += 1
    entry = {
        "no": round_no, "time": state.get("cut") or state["clock"], "order_nos": [o["order_no"] for o in picked], "sources": sources,
        "previous": {str(o["order_no"]): o["status"] for o in pool},  # 撤銷時還原
    }
    for order in pool:
        if order["order_no"] in picked_nos:
            order.update(status=FORMAL, round=round_no, shipment_no=new_shipment_no(rng, catalog, order["ship_type"]))
        else:  # 沒出的全部退回新訂單，再按比例重新抽急單、出貨中
            order["status"] = pull_status(rng, state)
    state["rounds"].append(entry)
    return entry


def undo(state):
    """撤銷最後一輪：那一輪之前在池子裡的單還原原本的位置。"""
    entry = state["rounds"].pop()
    previous = entry["previous"]
    for order in state["orders"]:
        status = previous.get(str(order["order_no"]))
        if status:
            order.update(status=status, round=None, shipment_no="")
    return entry


def summary(state):
    clock = parse(state["clock"])
    pools = {key: pool_orders(state, key) for key, _ in POOLS}
    waiting = pool_orders(state)
    return {
        "clock": clock,
        "started": parse(state["started"]),
        "counts": [(label, len(pools[key])) for key, label in POOLS],
        "formal_count": len(state["orders"]) - len(waiting),
        "cut": parse(state["cut"]) if state.get("cut") else None,
        "cut_count": len(cut_orders(state)),
        "due_today": sum(1 for o in waiting if due_date(o) <= clock.date()),
        "oldest": min((parse(o["created"]) for o in waiting), default=None),
        "rounds": [
            {**entry, "time": parse(entry["time"]), "count": len(entry["order_nos"]),
             "sources": [(label, entry["sources"][key]) for key, label in POOLS]}
            for entry in reversed(state["rounds"])
        ],
    }


def pools_zip(state):
    """截斷：記下截斷時間，目前的新訂單、急單、出貨中各一個 Excel 打包成 zip（沒有單的也放空檔，方便照常匯入）。
    呼叫的人要存檔（截斷時間要記住）。"""
    state["cut"] = state["clock"]
    stamp = parse(state["clock"]).strftime("%m%d_%H%M")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for key, label in POOLS:
            rows = [row for order in pool_orders(state, key) for row in order_rows(order)]
            archive.writestr(f"{label}_{stamp}.xlsx", workbook_bytes(rows))
    return buffer.getvalue(), f"訂單池_{stamp}.zip"


def round_file(state, round_no):
    entry = next(r for r in state["rounds"] if r["no"] == round_no)
    nos = set(entry["order_nos"])
    rows = [row for order in state["orders"] if order["order_no"] in nos
            for row in order_rows(order, order["shipment_no"])]
    stamp = parse(entry["time"]).strftime("%m%d_%H%M")
    return workbook_bytes(rows), f"正式訂單_第{round_no}輪_{stamp}.xlsx"
