from django import forms
from django.utils import timezone


class ImportForm(forms.Form):
    file = forms.FileField(label="訂單檔")
    work_date = forms.DateField(
        label="作業日", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="這批算進哪一天的資料池，預設今天。",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["work_date"].initial = timezone.localdate()
