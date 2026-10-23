"""測試用：預設職級（migration 建立的員工、組長、主任、經理）與建立帳號的捷徑。"""

from .models import Level as LevelModel, User

_RANKS = {"STAFF": 10, "LEADER": 20, "DIRECTOR": 30, "MANAGER": 40}


class _Levels:
    """Level.STAFF 等回傳預設職級的資料；Level.ADMIN 代表管理員帳號（不是職級）。"""

    ADMIN = "admin"

    def __getattr__(self, name):
        if name not in _RANKS:
            raise AttributeError(name)
        return LevelModel.objects.get(rank=_RANKS[name])


Level = _Levels()


def make_user(username, level=None, department=None, **extra):
    if level == Level.ADMIN:
        extra["is_admin"], level = True, None
    elif level is None:
        level = Level.STAFF
    return User.objects.create_user(username, password="pw12345!", name=username, level=level, department=department, **extra)
