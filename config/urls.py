from django.contrib import admin
from django.urls import path, include
from .views_auth import login_view, logout_view, otp_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include(("dashboard.urls", "dashboard"), namespace="dashboard")),

    path("login/", login_view, name="login"),
    path("otp/", otp_view, name="otp"),
    path("logout/", logout_view, name="logout"),

    path("policy/", include("policy.urls")),
    path("policy-history/", include("policy_history.urls")),
    path("ai/", include("ai_analysis_result.urls"), name="ai"),
    path("logs/", include("integrated_detection_logs.urls"), name="logs"),
]