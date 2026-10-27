"""選單：新增頁面時，在 MENU 加一筆即可出現在導覽列與頁面權限的選項中。
section="backoffice" 的頁面列在後台管理首頁（公司組織、帳號與權限這類設定）；section="feature" 的是獨立功能，在導覽列有自己的入口。"""

from dataclasses import dataclass

from apps.accounts.levels import is_admin
from apps.accounts.permissions import can_access


@dataclass(frozen=True)
class MenuItem:
    page_key: str
    label: str
    url_name: str
    group: str
    admin_only: bool = False  # 只有管理員能用，不受頁面權限設定影響
    section: str = "backoffice"


MENU = [
    MenuItem("attendance-register", "到班登記", "attendance:register", "到班", section="feature"),
    MenuItem("attendance-stations", "工位安排", "attendance:stations", "到班", section="feature"),
    MenuItem("order-stats", "訂單統計", "orders:run_list", "訂單", section="feature"),
    MenuItem("daily-stats", "當日統計", "daily:day_list", "訂單", section="feature"),
    MenuItem("manage-levels", "職級", "accounts_manage:level_list", "組織", admin_only=True),
    MenuItem("manage-departments", "部門", "accounts_manage:department_list", "組織"),
    MenuItem("manage-stations", "工位", "accounts_manage:station_list", "組織"),
    MenuItem("manage-employees", "人員資料", "personnel:employee_list", "帳號與權限"),
    MenuItem("manage-users", "系統帳號", "accounts_manage:user_list", "帳號與權限"),
    MenuItem("manage-page-permissions", "頁面權限", "accounts_manage:page_permission_list", "帳號與權限", admin_only=True),
    MenuItem("manage-level-rules", "職級規則", "accounts_manage:level_rule_list", "帳號與權限", admin_only=True),
    MenuItem("manage-clock-setting", "上下班時間", "attendance_manage:clock_setting", "到班設定"),
    MenuItem("manage-order-import", "匯入欄位對應", "orders_manage:version_list", "訂單"),
    MenuItem("manage-order-groups", "統計分組", "orders_manage:group_version_list", "訂單"),
    MenuItem("manage-order-categories", "匯入分類", "orders_manage:category_list", "訂單"),
]

MENU_BY_KEY = {item.page_key: item for item in MENU}


def can_use(user, item):
    return is_admin(user) if item.admin_only else can_access(user, item.page_key)


def accessible_menu(user, section=None):
    return [item for item in MENU if (section is None or item.section == section) and can_use(user, item)]
