from django.urls import path
from . import views

app_name = "policy_history"

urlpatterns = [
    path("", views.policy_history_list, name="list"),
    path("restore/<str:policy_id>/", views.policy_history_restore, name="restore"),
]
