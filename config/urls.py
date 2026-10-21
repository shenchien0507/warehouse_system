"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path

from apps.accounts import views as account_views

urlpatterns = [
    path("", account_views.home, name="home"),
    path("admin/", admin.site.urls),  # 僅供緊急備用，平常請用 /manage/
    path("accounts/", include("apps.accounts.urls")),
    path("manage/", include("apps.backoffice.urls")),
    path("manage/accounts/", include("apps.accounts.manage_urls")),
    path("manage/personnel/", include("apps.personnel.urls")),
]
