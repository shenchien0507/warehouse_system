from django import forms


class ImportForm(forms.Form):
    """匯入一律算進今天（系統日期），不能選作業日。"""

    file = forms.FileField(label="訂單檔")
