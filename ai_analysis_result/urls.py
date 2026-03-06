from django.urls import path
from .views import AiStatusView, AiStatusApiView, AiRecordsView, AiRecheckErrorsView

app_name = "ai"

urlpatterns = [
    path("records/", AiRecordsView.as_view(), name="records"),
    path("status/", AiStatusView.as_view(), name="status"),
    path("status/api/", AiStatusApiView.as_view(), name="status_api"),
    path("status/recheck/", AiRecheckErrorsView.as_view(), name="recheck_errors"),
]