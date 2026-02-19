from django.urls import path
from . import views

app_name = "logs"

urlpatterns = [
    path("", views.logs_list, name="list"),
]
