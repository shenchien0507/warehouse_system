from .menu import accessible_menu, split_features


def backoffice(request):
    """導覽列用：目前使用者能不能進後台，以及能用的獨立功能（分組）與工具。
    active_group 是目前頁面所屬的分組，依 url namespace 判斷，功能內的子頁面也會亮。"""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {"can_use_backoffice": False, "feature_groups": {}, "tool_menu": [], "active_group": None}
    feature_groups, tool_menu = split_features(accessible_menu(user, "feature"))
    match = getattr(request, "resolver_match", None)
    namespace = match.namespace if match else ""
    active_group = next(
        (group for group, items in feature_groups.items() if namespace and any(item.url_name.split(":")[0] == namespace for item in items)),
        None,
    )
    return {
        "can_use_backoffice": bool(accessible_menu(user, "backoffice")),
        "feature_groups": feature_groups,
        "tool_menu": tool_menu,
        "active_group": active_group,
    }
