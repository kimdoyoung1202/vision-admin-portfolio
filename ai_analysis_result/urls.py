from django.urls import path
from .views import AiStatusView, AiStatusApiView, AiRecordsView, AiIgnoreView, AiRecheckErrorsView

app_name = "ai"

urlpatterns = [
    path("records/", AiRecordsView.as_view(), name="records"),
    path("records/<int:pk>/ignore/", AiIgnoreView.as_view(), name="ignore"),
    path("status/", AiStatusView.as_view(), name="status"),
    path("status/api/", AiStatusApiView.as_view(), name="status_api"),

    # ✅ 재검토 버튼용
    path("status/recheck/", AiRecheckErrorsView.as_view(), name="recheck_errors"),
]