from django.core.exceptions import PermissionDenied

from .levels import is_admin
from .models import PagePermission


def can_access(user, page_key):
    """沒有設定過的頁面一律拒絕（管理員除外）。"""
    if is_admin(user):
        return True
    page = PagePermission.objects.select_related("min_level").filter(page_key=page_key).first()
    return page is not None and page.allows(user)


class PageAccessMixin:
    """class-based view 使用：設定 page_key，無權限回 403。需先登入（全站已預設需登入）。"""

    page_key = None

    def dispatch(self, request, *args, **kwargs):
        if not can_access(request.user, self.page_key):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def page_access_required(page_key):
    """function view 使用的裝飾器。"""

    def decorator(view):
        def wrapper(request, *args, **kwargs):
            if not can_access(request.user, page_key):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        wrapper.__name__ = view.__name__
        wrapper.__doc__ = view.__doc__
        return wrapper

    return decorator
