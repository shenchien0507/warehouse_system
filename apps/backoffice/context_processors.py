from .menu import accessible_menu


def backoffice(request):
    """導覽列用：目前使用者能不能進後台。"""
    user = getattr(request, "user", None)
    return {"can_use_backoffice": bool(user and user.is_authenticated and accessible_menu(user))}
