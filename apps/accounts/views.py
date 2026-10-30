from django.shortcuts import render


def home(request):
    """首頁：依導覽列同樣的分組列出能用的功能（資料來自 backoffice context processor）。"""
    return render(request, "home.html")
