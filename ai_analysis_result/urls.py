from django.urls import path
from . import views

app_name = "ai"

urlpatterns = [
    path("records/", views.ai_records, name="records"),
    path("status/", views.ai_status, name="status"),
]
