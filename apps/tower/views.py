"""「數據塔」：登記紀錄 → 撿貨 → 配貨的進度總覽，顯示最新一天，每分鐘自動更新。
每個種類一張數字卡（滑鼠停在上面會跳出詳細的各狀態），點進去（?kind=）單獨看那個種類。"""

from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.http import Http404
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
        kind = self.request.GET.get("kind") or None
        data = tower(kind=kind)
        if data is None:
            raise Http404("今天沒有這個種類")
        context.update(
            data,
            detail=kind,
            menu_item=MENU_BY_KEY[PAGE_KEY],
            refresh_seconds=REFRESH_SECONDS,
            refreshed_at=timezone.localtime(),
            partial_url=f"{self.request.path}?{urlencode({**({'kind': kind} if kind else {}), 'partial': 1})}",
        )
        return context
