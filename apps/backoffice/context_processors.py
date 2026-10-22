from .menu import accessible_menu


def backoffice(request):
    """導覽列用：目前使用者能不能進後台，以及能用的獨立功能頁面。"""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {"can_use_backoffice": False, "feature_menu": []}
    return {
        "can_use_backoffice": bool(accessible_menu(user, "backoffice")),
        "feature_menu": accessible_menu(user, "feature"),
    }
