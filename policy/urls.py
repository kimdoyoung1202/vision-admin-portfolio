from django.urls import path
from . import views

app_name = "policy"

urlpatterns = [
    path("", views.policy_list, name="list"),
    path("add/", views.policy_add, name="add"),
    path("delete/<str:policy_id>/", views.policy_delete, name="delete"),
    path("update/<str:policy_id>/", views.policy_update, name="update"),
]
