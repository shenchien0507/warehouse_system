"""數據塔：把當日統計（今天每個種類應出的總數）、登記紀錄（登記進哪個種類）、撿貨登記、配貨登記串起來看進度。
沒有自己的資料表，每次現算。種類就是統計分組的名稱，登記時選；編號只是代號，不看格式，
撿貨、配貨靠編號對得到登記紀錄的那一筆。看的是目前的作業日（closing.workday：沒開結轉就是系統日期的今天）。

結轉（後台設了結轉起算日才有）：前面作業日沒做完的也算進今天。
- 前日待印：上一次日結當下的待印（數量），今天登記時先扣它（先印舊的）。
- 前日的編號：起算日以後登記、在今天之前還沒配貨完成的，照撿貨、配貨的狀態繼續算。
所以每個種類今天的總數 = 今天當日統計匯入的 + 前日待印 + 前日還沒做完的編號。"""

from collections import OrderedDict
from dataclasses import dataclass, field

from apps.closing.workday import carry_start, current_work_date, last_close
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


# 日結、昨日未完成用的三種：待撿 = 未開始＋撿貨進行中；待包 = 未配貨＋配貨進行中（待印就是未登記）
TO_PICK, TO_PACK = (NOT_STARTED, PICKING), (WAIT_ALLOCATION, ALLOCATING)


@dataclass
class KindBoard:
    name: str
    total: int = 0  # 今天要做的全部：當日統計今天匯入的 + 前日轉來的；沒有當日統計的種類（例如未分類）用登記的數量
    has_total: bool = False  # 當日統計有這個種類（今天或前日）
    registered: int = 0  # 板上的編號數量（今天登記的 + 前日還沒做完的）
    count: int = 0  # 登記了幾個編號
    states: dict = field(default_factory=lambda: OrderedDict((key, [0, 0]) for key, _ in STATES))  # 狀態 → [數量, 幾個編號]
    today: int = 0  # 當日統計今天匯入的
    carried_unprinted: int = 0  # 上次日結的待印
    registered_today: int = 0  # 今天登記的數量
    prior: dict = field(default_factory=lambda: OrderedDict((key, 0) for key, _ in STATES))  # 前日的部分：狀態 → 數量

    @property
    def limit(self):
        """今天最多可以登記多少：今天匯入的 + 前日待印。"""
        return self.today + self.carried_unprinted

    @property
    def carried(self):
        """開工時從前面轉來的：前日待印 + 前日還沒做完的編號。"""
        return self.carried_unprinted + sum(self.prior[key] for key, _ in STATES if key != UNREGISTERED)

    @property
    def today_part(self):
        """總數裡今天的部分（總數扣掉前日轉來的）。"""
        return self.total - self.carried

    @property
    def carried_left(self):
        """前日轉來的現在還剩多少（還沒配貨完成）。"""
        return sum(self.prior[key] for key, _ in STATES if key != DONE)

    @property
    def done(self):
        return self.states[DONE][0]

    @property
    def remaining(self):
        return self.total - self.done

    @property
    def to_pick(self):
        return sum(self.states[key][0] for key in TO_PICK)

    @property
    def to_pack(self):
        return sum(self.states[key][0] for key in TO_PACK)

    @property
    def over_by(self):
        """今天登記的比可以登記的多出來的數量。"""
        return max(0, self.registered_today - self.limit) if self.has_total else 0

    @property
    def percent(self):
        return max(0, min(100, self.done * 100 / self.total)) if self.total > 0 else 0

    @property
    def rows(self):
        """[(狀態, 名稱, 數量, 幾個編號, 長條寬度%, 前日的數量)]"""
        return [(key, label, *self.states[key], self._width(self.states[key][0]), self.prior[key]) for key, label in STATES]

    def _width(self, quantity):
        return max(0, quantity) * 100 / max(self.total, self.registered) if self.total > 0 or self.registered > 0 else 0


def latest_by_number(stage, numbers):
    """每個編號在這個階段最新的一筆登記。"""
    latest = {}
    for entry in WorkEntry.objects.filter(stage=stage, number__in=numbers).select_related("start_employee", "end_employee").prefetch_related("segments__employee").order_by("started_at", "pk"):
        latest[entry.number] = entry
    return latest


def work_date():
    """目前的作業日：沒開結轉就是系統日期的今天，開了就是還沒日結的那天。"""
    return current_work_date()


def totals_by_kind(day):
    """當日統計那天各種類的總數（卡片上的大數字）：({種類: 總數}, 種類順序)。"""
    batches, summary = day_stats(day)
    if not batches:
        return {}, []
    cards = dashboard(batches, summary, version_groups(batches[0].group_version)).groups
    return {card.name: card.main for card in cards}, [card.name for card in cards]


def carried_unprinted(day):
    """({種類: 上次日結的待印}, 上次日結)；沒開結轉或之前沒日結過是 ({}, None)。"""
    close = last_close(before=day)
    if close is None:
        return {}, None
    return {k["name"]: k["unprinted"] for k in close.kinds if k.get("unprinted")}, close


def kind_limits(day):
    """登記用：OrderedDict {種類: (今天已登記, 今天最多可以登記)}，當日統計今天有的種類加上有前日待印的種類。"""
    from apps.records.rules import registered_by_kind

    totals, order = totals_by_kind(day)
    unprinted, _ = carried_unprinted(day)
    registered = registered_by_kind(day)
    names = [*order, *(name for name in unprinted if name not in totals)]
    return OrderedDict((name, (registered.get(name, 0), totals.get(name, 0) + unprinted.get(name, 0))) for name in names)


def board_records(day):
    """(今天登記的紀錄, 前日還沒做完的紀錄)。前日的只有開了結轉才有：起算日以後、今天之前登記，在今天之前還沒配貨完成的。"""
    today = list(Record.objects.of_day(day).only("number", "quantity", "kind", "work_date"))
    start = carry_start()
    if start is None or start >= day:
        return today, []
    finished = WorkEntry.objects.filter(stage=Stage.ALLOCATION, ended_at__isnull=False, end_work_date__lt=day).values("number")
    prior = list(
        Record.objects.filter(work_date__gte=start, work_date__lt=day).exclude(number__in=finished)
        .only("number", "quantity", "kind", "work_date")
    )
    return today, prior


def boards_for(day):
    """（OrderedDict {種類: KindBoard}, 板上的紀錄（今天的 + 前日的）, 撿貨最新, 配貨最新）。"""
    totals, order = totals_by_kind(day)
    unprinted, close = carried_unprinted(day)
    closed_kinds = {k["name"] for k in close.kinds} if close else set()
    today_records, prior_records = board_records(day)
    records = today_records + prior_records
    numbers = [r.number for r in records]
    picking = latest_by_number(Stage.PICKING, numbers)
    allocation = latest_by_number(Stage.ALLOCATION, numbers)

    boards = OrderedDict()
    for name in [*order, *unprinted]:
        if name not in boards:
            boards[name] = KindBoard(name, has_total=True, today=totals.get(name, 0), carried_unprinted=unprinted.get(name, 0))
    for record in sorted(records, key=lambda r: r.number):
        name = record.kind or UNCLASSIFIED
        board = boards.setdefault(name, KindBoard(name, has_total=name in closed_kinds))
        state = state_of(picking.get(record.number), allocation.get(record.number))
        board.registered += record.quantity
        board.count += 1
        board.states[state][0] += record.quantity
        board.states[state][1] += 1
        if record.work_date == day:
            board.registered_today += record.quantity
        else:
            board.prior[state] += record.quantity
    for board in boards.values():
        prior_records_quantity = board.registered - board.registered_today
        if board.has_total:
            board.total = board.limit + prior_records_quantity
            unregistered = max(0, board.limit - board.registered_today)
        else:
            board.total = board.registered
            unregistered = 0
        board.states[UNREGISTERED][0] = unregistered
        # 先印舊的：今天登記的先扣前日待印
        board.prior[UNREGISTERED] = min(unregistered, max(0, board.carried_unprinted - board.registered_today))
    return boards, records, picking, allocation


def tower(kind=None):
    """kind 有值只看那個種類（單獨頁）：卡片、進行中、完成、編號清單都只留這個種類的；沒有這個種類回傳 None。
    picking / allocation 是撿貨、配貨進行中，done 是配貨完成，都是新的在前；畫面上先列 5 筆，其他收起來。
    前日登記的編號帶著 prior_date（登記的作業日），畫面上標日期。"""
    day = work_date()
    boards, records, picking, allocation = boards_for(day)
    prior_dates = {r.number: r.work_date for r in records if r.work_date and r.work_date != day}
    for entry in [*picking.values(), *allocation.values()]:
        entry.prior_date = prior_dates.get(entry.number)

    listing = [
        (r.number, r.kind or UNCLASSIFIED, r.quantity, dict(STATES)[s], s, prior_dates.get(r.number))
        for r in sorted(records, key=lambda r: r.number)
        for s in [state_of(picking.get(r.number), allocation.get(r.number))]
    ]
    picking_active = sorted((e for e in picking.values() if e.ended_at is None), key=lambda e: e.started_at, reverse=True)
    allocation_active = sorted((e for e in allocation.values() if e.ended_at is None), key=lambda e: e.started_at, reverse=True)
    done = sorted((e for e in allocation.values() if e.ended_at is not None), key=lambda e: e.ended_at, reverse=True)
    if kind is not None:
        if kind not in boards:
            return None
        mine = {r.number for r in records if (r.kind or UNCLASSIFIED) == kind}
        boards = OrderedDict([(kind, boards[kind])])
        listing = [row for row in listing if row[0] in mine]
        picking_active, allocation_active, done = (
            [e for e in entries if e.number in mine] for entries in (picking_active, allocation_active, done)
        )
    return {
        "work_date": day, "kinds": list(boards.values()), "numbers": listing,
        "progress": [
            ("picking", "撿貨進行中", "開始", picking_active, "現在沒有撿貨中的編號。"),
            ("allocation", "配貨進行中", "開始", allocation_active, "現在沒有配貨中的編號。"),
            ("done", "配貨完成", "完成", done, "還沒有配貨完成的編號。"),
        ],
    }


def kind_cards():
    """登記紀錄頁最上面的種類卡：(作業日, [(種類, 已登記, 可以登記的總數)])。
    種類是當日統計今天有數字卡的，加上有前日待印的；總數 = 今天匯入的 + 前日待印。"""
    day = work_date()
    return day, [(name, registered, limit) for name, (registered, limit) in kind_limits(day).items()]
