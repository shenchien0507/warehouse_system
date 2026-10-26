from django.urls import path

from . import views

app_name = "orders_manage"

urlpatterns = [
    path("templates/", views.TemplateList.as_view(), name="template_list"),
    path("templates/new/", views.TemplateCreate.as_view(), name="template_create"),
    path("templates/<int:pk>/", views.TemplateUpdate.as_view(), name="template_edit"),
    path("templates/<int:pk>/delete/", views.TemplateDelete.as_view(), name="template_delete"),
    path("templates/<int:pk>/test/", views.TemplateTest.as_view(), name="template_test"),
]
