"""工位安排的編輯鎖：有人在編輯時，其他帳號只能查看，不能進入編輯。"""

import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import StationEditLock

LOCK_PK = 1  # 全系統只有一把鎖


def expires(lock):
    return lock.touched_at + datetime.timedelta(minutes=StationEditLock.LOCK_MINUTES)


def current_lock():
    """目前有效的編輯鎖；沒有人在編輯（或已逾時）回傳 None。"""
    lock = StationEditLock.objects.select_related("user").filter(pk=LOCK_PK).first()
    return lock if lock and expires(lock) > timezone.now() else None


def held_by_other(user):
    """別的帳號正在編輯時回傳那把鎖，否則回傳 None。"""
    lock = current_lock()
    return lock if lock and lock.user_id != user.pk else None


def acquire(user, date):
    """取得編輯鎖；回傳 (是否取得, 鎖)。同一個帳號可以重複取得（例如開兩個分頁）。"""
    now = timezone.now()
    try:
        with transaction.atomic():
            lock = StationEditLock.objects.select_for_update().select_related("user").filter(pk=LOCK_PK).first()
            if lock is None:
                return True, StationEditLock.objects.create(pk=LOCK_PK, user=user, date=date, started_at=now, touched_at=now)
            active = expires(lock) > now
            if active and lock.user_id != user.pk:
                return False, lock
            if not active or lock.user_id != user.pk:
                lock.started_at = now
            lock.user, lock.date, lock.touched_at = user, date, now
            lock.save()
            return True, lock
    except IntegrityError:  # 兩個人同時建立第一把鎖
        return False, current_lock()


def release(user=None):
    """放開自己的鎖；user 為 None 時強制解除（不管是誰的）。"""
    locks = StationEditLock.objects.filter(pk=LOCK_PK)
    if user is not None:
        locks = locks.filter(user=user)
    locks.delete()
