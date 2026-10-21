"""後台選單：新增後台頁面時，在 MENU 加一筆即可出現在後台首頁、導覽列與頁面權限的選項中。"""

from dataclasses import dataclass

from apps.accounts.models import Level
from apps.accounts.permissions import can_access


@dataclass(frozen=True)
class MenuItem:
    page_key: str
    label: str
    url_name: str
    group: str
    admin_only: bool = False  # 只有管理員能用，不受頁面權限設定影響


MENU = [
    MenuItem("attendance-register", "到班登記", "attendance:register", "到班"),
    MenuItem("attendance-headcount", "到班人數", "attendance:headcount", "到班"),
    MenuItem("manage-employees", "人員資料", "personnel:employee_list", "人員"),
    MenuItem("manage-job-titles", "職務", "personnel:job_title_list", "人員"),
    MenuItem("manage-departments", "部門", "accounts_manage:department_list", "組織"),
    MenuItem("manage-stations", "工位", "accounts_manage:station_list", "組織"),
    MenuItem("manage-users", "系統帳號", "accounts_manage:user_list", "帳號與權限"),
    MenuItem("manage-page-permissions", "頁面權限", "accounts_manage:page_permission_list", "帳號與權限", admin_only=True),
]

MENU_BY_KEY = {item.page_key: item for item in MENU}


def is_admin(user):
    return user.is_authenticated and user.is_active and user.level == Level.ADMIN


def can_use(user, item):
    return is_admin(user) if item.admin_only else can_access(user, item.page_key)


def accessible_menu(user):
    return [item for item in MENU if can_use(user, item)]
