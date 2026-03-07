from django.urls import path
from .views import AiRecordsView, AiStatusView, AiStatusApiView, AiRecheckErrorsView, AiIgnoreView

app_name = "ai"

urlpatterns = [
    path("records/", AiRecordsView.as_view(), name="records"),
    path("records/<int:pk>/ignore/", AiIgnoreView.as_view(), name="ignore"),
    path("status/", AiStatusView.as_view(), name="status"),
    path("status/api/", AiStatusApiView.as_view(), name="status_api"),
    path("recheck-errors/", AiRecheckErrorsView.as_view(), name="recheck_errors"),
]