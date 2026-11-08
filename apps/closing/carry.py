"""日結的數字和「昨日未完成」。

- snapshot(day)：日結當下每個種類的數字，存進 DayClose。
- carry_report(day)：day 開工時從上一次日結轉來的待印、待撿、待包（固定，不會變），
  day 是目前作業日時另外算「目前還剩」（今天做掉的即時扣掉）。當日統計、訂單統計都用它。"""

from dataclasses import dataclass, field

from apps.tower.stats import DONE, UNREGISTERED, boards_for

from .workday import current_work_date, last_close


def snapshot(day):
    boards, _, _, _ = boards_for(day)
    kinds = []
    for board in boards.values():
        row = {
            "name": board.name,
            "today": board.today,
            "carried": board.carried,
            "done": board.states[DONE][0],
            "unprinted": board.states[UNREGISTERED][0],
            "picking": board.to_pick,
            "packing": board.to_pack,
        }
        if any(row[key] for key in ("today", "carried", "done", "unprinted", "picking", "packing")):
            kinds.append(row)
    return {"kinds": kinds}


@dataclass
class CarryRow:
    name: str
    unprinted: int
    picking: int
    packing: int
    left: int = None  # 目前還剩（只有看目前作業日才算）

    @property
    def total(self):
        return self.unprinted + self.picking + self.packing


@dataclass
class CarryReport:
    close: object  # 上一次日結（DayClose）
    rows: list = field(default_factory=list)  # 有轉過來的種類（都是 0 的不列）
    live: bool = False  # 有沒有算「目前還剩」

    def _sum(self, attr):
        return sum(getattr(row, attr) or 0 for row in self.rows)

    @property
    def unprinted(self):
        return self._sum("unprinted")

    @property
    def picking(self):
        return self._sum("picking")

    @property
    def packing(self):
        return self._sum("packing")

    @property
    def total(self):
        return self._sum("total")

    @property
    def left(self):
        return self._sum("left")

    def by_name(self):
        return {row.name: row for row in self.rows}


def carry_report(day):
    """day 的「昨日未完成」；沒開結轉、之前沒日結過、或上次日結什麼都沒剩，回傳 None。"""
    close = last_close(before=day)
    if close is None:
        return None
    rows = [
        CarryRow(k["name"], k.get("unprinted", 0), k.get("picking", 0), k.get("packing", 0))
        for k in close.kinds
    ]
    rows = [row for row in rows if row.total]
    if not rows:
        return None
    report = CarryReport(close=close, rows=rows)
    if day == current_work_date():
        boards, _, _, _ = boards_for(day)
        for row in rows:
            board = boards.get(row.name)
            row.left = board.carried_left if board else 0
        report.live = True
    return report
