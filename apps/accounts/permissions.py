"""頁面權限：view 用 apps.backoffice.views.PageMixin 檢查（它會再呼叫這裡的 can_access）。"""

from .levels import is_admin
from .models import PagePermission


def can_access(user, page_key):
    """沒有設定過的頁面一律拒絕（管理員除外）。"""
    if is_admin(user):
        return True
    page = PagePermission.objects.select_related("min_level").filter(page_key=page_key).first()
    return page is not None and page.allows(user)
