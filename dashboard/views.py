from django.contrib.auth.decorators import login_required
from django.shortcuts import render

@login_required
def dashboard_view(request):
    return render(request, "dashboard/dashboard.html", {
        "active_menu": "dashboard",
        "active_group": "dashboard",
    })