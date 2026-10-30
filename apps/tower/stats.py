"""數據塔：把當日統計（今天每個種類應出的總數）、登記紀錄（登記進哪個種類）、撿貨登記、配貨登記串起來看進度。
沒有自己的資料表，每次現算。種類就是統計分組的名稱，登記時選；編號只是代號，不看格式，
撿貨、配貨靠編號對得到登記紀錄的那一筆。今天一律是系統日期的今天。"""

from collections import OrderedDict
from dataclasses import dataclass, field

from django.utils import timezone

from apps.daily.stats import dashboard, day_stats
from apps.orders.stats import version_groups
from apps.records.models import Record
from apps.worklog.models import Stage, WorkEntry

# 狀態依序：還沒登記 → 還沒開始 → 撿貨進行中 → 未配貨（撿完等配貨）→ 配貨進行中 → 完成（配貨結束才算整體完成）
UNREGISTERED, NOT_STARTED, PICKING, WAIT_ALLOCATION, ALLOCATING, DONE = (
    "unregistered", "not_started", "picking", "wait_allocation", "allocating", "done",
)
STATES = [
    (UNREGISTERED, "未登記"),
    (NOT_STARTED, "未開始"),
    (PICKING, "撿貨進行中"),
    (WAIT_ALLOCATION, "未配貨"),
    (ALLOCATING, "配貨進行中"),
    (DONE, "完成"),
]
UNCLASSIFIED = "未分類"


def state_of(picking, allocation):
    """picking、allocation 是該編號各階段最新一筆登記（沒有就是 None）。配貨有登記時以配貨為準。"""
    if allocation is not None:
        return ALLOCATING if allocation.ended_at is None else DONE
    if picking is None:
        return NOT_STARTED
    return PICKING if picking.ended_at is None else WAIT_ALLOCATION


@dataclass
class KindBoard:
    name: str
    total: int = 0  # 當日統計今天累計的總數；沒有當日統計的種類（例如未分類）用登記的數量
    has_total: bool = False  # 當日統計有這個種類
    registered: int = 0
    count: int = 0  # 登記了幾個編號
    states: dict = field(default_factory=lambda: OrderedDict((key, [0, 0]) for key, _ in STATES))  # 狀態 → [數量, 幾個編號]

    @property
    def done(self):
        return self.states[DONE][0]

    @property
    def remaining(self):
        return self.total - self.done

    @property
    def over_by(self):
        """登記比當日統計總數多出來的數量。"""
        return max(0, self.registered - self.total) if self.has_total else 0

    @property
    def percent(self):
        return max(0, min(100, self.done * 100 / self.total)) if self.total > 0 else 0

    @property
    def rows(self):
        return [(key, label, *self.states[key], self._width(self.states[key][0])) for key, label in STATES]

    def _width(self, quantity):
        return max(0, quantity) * 100 / max(self.total, self.registered) if self.total > 0 or self.registered > 0 else 0


def latest_by_number(stage, numbers):
    """每個編號在這個階段最新的一筆登記。"""
    latest = {}
    for entry in WorkEntry.objects.filter(stage=stage, number__in=numbers).select_related("start_employee").order_by("started_at", "pk"):
        latest[entry.number] = entry
    return latest


def work_date():
    """系統操作一律看今天（系統日期），不跟著最新匯入的作業日跑。"""
    return timezone.localdate()


def totals_by_kind(day):
    """當日統計今天各種類的總數（卡片上的大數字）：({種類: 總數}, 種類順序)。"""
    batches, summary = day_stats(day)
    if not batches:
        return {}, []
    cards = dashboard(batches, summary, version_groups(batches[0].group_version)).groups
    return {card.name: card.main for card in cards}, [card.name for card in cards]


def tower(limit_recent=5, kind=None):
    """kind 有值只看那個種類（單獨頁）：卡片、進行中、最近完成、編號清單都只留這個種類的；沒有這個種類回傳 None。"""
    day = work_date()
    totals, order = totals_by_kind(day)
    records = list(Record.objects.created_on(day).only("number", "quantity", "kind"))
    numbers = [r.number for r in records]
    picking = latest_by_number(Stage.PICKING, numbers)
    allocation = latest_by_number(Stage.ALLOCATION, numbers)

    boards = OrderedDict()
    for name in order:
        boards[name] = KindBoard(name, total=totals[name], has_total=True)
    for record in sorted(records, key=lambda r: r.number):
        name = record.kind or UNCLASSIFIED
        board = boards.setdefault(name, KindBoard(name))
        state = state_of(picking.get(record.number), allocation.get(record.number))
        board.registered += record.quantity
        board.count += 1
        board.states[state][0] += record.quantity
        board.states[state][1] += 1
    for board in boards.values():
        if not board.has_total:
            board.total = board.registered
        board.states[UNREGISTERED][0] = max(0, board.total - board.registered)

    listing = [
        (r.number, r.kind or UNCLASSIFIED, r.quantity, dict(STATES)[s], s)
        for r in sorted(records, key=lambda r: r.number)
        for s in [state_of(picking.get(r.number), allocation.get(r.number))]
    ]
    active = [
        (entry, "撿貨" if stage == Stage.PICKING else "配貨")
        for stage, entries in ((Stage.PICKING, picking), (Stage.ALLOCATION, allocation))
        for entry in entries.values()
        if entry.ended_at is None
    ]
    active.sort(key=lambda item: item[0].started_at)
    recent = sorted((e for e in allocation.values() if e.ended_at is not None), key=lambda e: e.ended_at, reverse=True)[:limit_recent]
    if kind is not None:
        if kind not in boards:
            return None
        mine = {r.number for r in records if (r.kind or UNCLASSIFIED) == kind}
        boards = OrderedDict([(kind, boards[kind])])
        listing = [row for row in listing if row[0] in mine]
        active = [item for item in active if item[0].number in mine]
        recent = [e for e in sorted((e for e in allocation.values() if e.ended_at is not None and e.number in mine), key=lambda e: e.ended_at, reverse=True)][:limit_recent]
    return {"work_date": day, "kinds": list(boards.values()), "active": active, "recent": recent, "numbers": listing}


def kind_cards():
    """登記紀錄頁最上面的種類卡：(今天, [(種類, 已登記, 總數)])，只有當日統計今天有數字的種類。"""
    from apps.records.rules import registered_by_kind

    day = work_date()
    totals, order = totals_by_kind(day)
    registered = registered_by_kind(day)
    return day, [(name, registered.get(name, 0), totals[name]) for name in order]
