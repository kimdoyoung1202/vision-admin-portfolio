from django.urls import path
from . import views

app_name = "policy_delete_history"

urlpatterns = [
    path("", views.policy_delete_history_list, name="list"),
    path("restore/<int:history_id>/", views.policy_delete_history_restore, name="restore"),
]