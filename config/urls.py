"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
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
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),

    # ✅ 임시 대시보드
    path("", TemplateView.as_view(template_name="dashboard.html"), name="dashboard"),

    # ✅ 로그아웃 (auth 미들웨어/앱이 settings에 있어야 함)
    path("logout/", auth_views.LogoutView.as_view(next_page="/"), name="logout"),

    # ✅ 각 앱 임시 페이지
    path("policy/", include("policy.urls")),
    path("policy-history/", include("policy_history.urls")),
    path("ai/", include("ai_analysis_result.urls")),
    path("logs/", include("intergrated_detection_logs.urls")),
]