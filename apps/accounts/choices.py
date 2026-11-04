"""職級、部門、工位可以停用：停用的不再出現在新的選單裡，但舊紀錄照樣保留、照樣顯示。"""

from django import forms
from django.db.models import Model, Q


def _pks(value):
    if callable(value) and not hasattr(value, "all"):
        value = value()
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)) or hasattr(value, "all"):
        items = value.all() if hasattr(value, "all") else value
        return [pk for item in items for pk in _pks(item)]
    return [value.pk if isinstance(value, Model) else value]


def hide_inactive_choices(form):
    """把表單裡職級、部門、工位的選項限縮成啟用中的；目前已經選的（例如舊資料用的已停用項目）保留，不會被清掉。"""
    from .models import Department, Level, Station

    for name, field in form.fields.items():
        if not isinstance(field, forms.ModelChoiceField):
            continue
        if field.queryset.model not in (Level, Department, Station):
            continue
        current = _pks(form.initial.get(name, field.initial))
        field.queryset = field.queryset.filter(Q(is_active=True) | Q(pk__in=current))
    return form
