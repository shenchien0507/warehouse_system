from django.shortcuts import render

from .permissions import accessible_pages


def home(request):
    return render(request, "home.html", {"pages": accessible_pages(request.user)})
