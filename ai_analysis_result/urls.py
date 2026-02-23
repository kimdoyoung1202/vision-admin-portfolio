from django.urls import path
from . import views
from .views import AiStatusView, AiStatusApiView

app_name = "ai"

urlpatterns = [
    path("records/", views.AiRecordsView.as_view(), name="records"),   # AI 기록관
    path("status/", views.AiStatusView.as_view(), name="status"),    # AI 성능 현황 (나중에)
    path("records/<int:pk>/ignore/", views.AiIgnoreView.as_view(), name="ignore"), # 무시
    path("status/api/", views.AiStatusApiView.as_view(), name="status_api"),
]
