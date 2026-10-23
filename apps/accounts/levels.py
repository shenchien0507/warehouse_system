"""職級高低的判斷。職級存在 Level 資料表，規則門檻存在 LevelRule，程式裡不寫死任何職級。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    code: str
    label: str
    default_rank: int  # 預設門檻（對應預設職級的排序），建立規則資料時使用


# 新增依職級判斷的規則：在這裡加一筆，再到後台「職級規則」設定門檻
RULES = [
    Rule("attendance-register-own", "到班：登記自己部門的人員", 20),
    Rule("attendance-register-all", "到班：登記全部部門的人員、看「未設定部門」", 40),
    Rule("attendance-past-dates", "到班：修改之前日期的紀錄與工位、作廢別人登記的紀錄", 30),
    Rule("attendance-stations-all", "工位安排：安排全部部門", 40),
]

RULES_BY_CODE = {rule.code: rule for rule in RULES}


def is_admin(user):
    return bool(user.is_authenticated and user.is_active and (user.is_admin or user.is_superuser))


def rank_of(level):
    return level.rank if level is not None else 0


def reaches(user, level):
    """使用者的職級是否到達 level（含）。level 為 None 時只有管理員可以。"""
    if is_admin(user):
        return True
    if level is None or not user.is_authenticated or user.level_id is None:
        return False
    return user.level.rank >= level.rank


def outranks(editor, level):
    """editor 的職級是否比 level 高：非管理員只能管理、設定比自己低的職級。"""
    if is_admin(editor):
        return True
    return editor.level_id is not None and editor.level.rank > rank_of(level)


def levels_below(editor):
    from .models import Level

    if is_admin(editor):
        return Level.objects.all()
    if editor.level_id is None:
        return Level.objects.none()
    return Level.objects.filter(rank__lt=editor.level.rank)


def rule_level(code):
    from .models import LevelRule

    rule = LevelRule.objects.select_related("min_level").filter(code=code).first()
    return rule.min_level if rule else None


def allows(user, code):
    """依「職級規則」判斷；沒設定門檻的規則只有管理員可以。"""
    assert code in RULES_BY_CODE, code
    return is_admin(user) or reaches(user, rule_level(code))
