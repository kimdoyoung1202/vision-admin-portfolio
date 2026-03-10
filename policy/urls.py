from django.urls import path
from . import views

app_name = "policy"

urlpatterns = [
    path("", views.policy_list, name="list"),
    path("add/", views.policy_add, name="add"),
    path("delete/<int:policy_id>/", views.policy_delete, name="delete"),
    path("update/<int:policy_id>/", views.policy_update, name="update"),
    path("edit-ajax/<int:policy_id>/", views.policy_edit_ajax, name="edit_ajax"),
]