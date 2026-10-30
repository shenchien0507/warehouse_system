"""「數據塔」：登記紀錄 → 撿貨 → 配貨的進度總覽，顯示最新一天，每分鐘自動更新。"""

from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.views.generic import TemplateView

from apps.backoffice.menu import MENU_BY_KEY, can_use

from .stats import tower

PAGE_KEY = "data-tower"
REFRESH_SECONDS = 60


class TowerView(TemplateView):
    """GET ?partial=1 只回進度區塊，給頁面定時更新用。"""

    template_name = "tower/index.html"

    def dispatch(self, request, *args, **kwargs):
        if not can_use(request.user, MENU_BY_KEY[PAGE_KEY]):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_template_names(self):
        return ["tower/_board.html"] if self.request.GET.get("partial") else [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            tower(),
            menu_item=MENU_BY_KEY[PAGE_KEY],
            refresh_seconds=REFRESH_SECONDS,
            refreshed_at=timezone.localtime(),
            partial_url=f"{self.request.path}?partial=1",
        )
        return context
