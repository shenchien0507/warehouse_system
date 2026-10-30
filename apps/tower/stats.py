"""數據塔：把登記紀錄、撿貨登記、配貨登記用編號串起來，看最新一天的進度。沒有自己的資料表，每次現算。
編號格式 yymmdd-001 是一般配（數量是訂單數），yymmdd-W01 是無包裝（數量是 pcs）；格式對不上的不計入。"""

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date

from apps.records.models import Record
from apps.worklog.models import Stage, WorkEntry

NUMBER_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})-(W?)\d+$", re.IGNORECASE)

NORMAL, UNPACKAGED = "normal", "unpackaged"
KINDS = [(NORMAL, "一般配", "張訂單"), (UNPACKAGED, "無包裝", "pcs")]

# 狀態依序：還沒開始 → 撿貨進行中 → 未配貨（撿完等配貨）→ 配貨進行中 → 完成（配貨結束才算整體完成）
NOT_STARTED, PICKING, WAIT_ALLOCATION, ALLOCATING, DONE = "not_started", "picking", "wait_allocation", "allocating", "done"
STATES = [
    (NOT_STARTED, "未開始"),
    (PICKING, "撿貨進行中"),
    (WAIT_ALLOCATION, "未配貨"),
    (ALLOCATING, "配貨進行中"),
    (DONE, "完成"),
]


def parse_number(number):
    """回傳 (日期, 類別)；格式或日期不對回傳 None。"""
    match = NUMBER_RE.match(number.strip())
    if not match:
        return None
    yy, mm, dd, w = match.groups()
    try:
        day = date(2000 + int(yy), int(mm), int(dd))
    except ValueError:
        return None
    return day, UNPACKAGED if w else NORMAL


def state_of(picking, allocation):
    """picking、allocation 是該編號各階段最新一筆登記（沒有就是 None）。配貨有登記時以配貨為準。"""
    if allocation is not None:
        return ALLOCATING if allocation.ended_at is None else DONE
    if picking is None:
        return NOT_STARTED
    return PICKING if picking.ended_at is None else WAIT_ALLOCATION


@dataclass
class KindBoard:
    key: str
    label: str
    unit: str
    total: int = 0
    count: int = 0
    states: dict = field(default_factory=lambda: OrderedDict((key, [0, 0]) for key, _ in STATES))  # 狀態 → [數量, 幾份]

    @property
    def done(self):
        return self.states[DONE][0]

    @property
    def remaining(self):
        return self.total - self.done

    @property
    def percent(self):
        return max(0, min(100, self.done * 100 / self.total)) if self.total > 0 else 0

    @property
    def rows(self):
        return [(key, label, *self.states[key], self._width(self.states[key][0])) for key, label in STATES]

    def _width(self, quantity):
        return max(0, quantity) * 100 / self.total if self.total > 0 else 0


def latest_by_number(stage, numbers):
    """每個編號在這個階段最新的一筆登記。"""
    latest = {}
    for entry in WorkEntry.objects.filter(stage=stage, number__in=numbers).select_related("start_employee").order_by("started_at", "pk"):
        latest[entry.number] = entry
    return latest


def tower(limit_recent=5):
    """最新一天的進度。沒有任何符合格式的登記紀錄時 work_date 是 None。"""
    parsed = {}
    skipped = 0
    for record in Record.objects.only("number", "quantity"):
        info = parse_number(record.number)
        if info is None:
            skipped += 1
        else:
            parsed[record.number] = (record, *info)
    if not parsed:
        return {"work_date": None, "skipped": skipped, "kinds": [], "active": [], "recent": [], "numbers": []}

    work_date = max(day for _, day, _ in parsed.values())
    today = {number: item for number, item in parsed.items() if item[1] == work_date}
    numbers = list(today)
    picking = latest_by_number(Stage.PICKING, numbers)
    allocation = latest_by_number(Stage.ALLOCATION, numbers)

    boards = OrderedDict((key, KindBoard(key, label, unit)) for key, label, unit in KINDS)
    listing = []
    for number in sorted(today):
        record, _, kind = today[number]
        state = state_of(picking.get(number), allocation.get(number))
        board = boards[kind]
        board.total += record.quantity
        board.count += 1
        board.states[state][0] += record.quantity
        board.states[state][1] += 1
        listing.append((number, boards[kind].label, record.quantity, dict(STATES)[state], state))

    active = [
        (entry, "撿貨" if stage == Stage.PICKING else "配貨")
        for stage, entries in ((Stage.PICKING, picking), (Stage.ALLOCATION, allocation))
        for entry in entries.values()
        if entry.ended_at is None
    ]
    active.sort(key=lambda item: item[0].started_at)
    recent = sorted((e for e in allocation.values() if e.ended_at is not None), key=lambda e: e.ended_at, reverse=True)[:limit_recent]
    return {
        "work_date": work_date,
        "skipped": skipped,
        "kinds": [b for b in boards.values() if b.count],
        "active": active,
        "recent": recent,
        "numbers": listing,
    }
