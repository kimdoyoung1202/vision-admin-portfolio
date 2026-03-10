from django.urls import path
from . import views

app_name = 'policy_update_history'

urlpatterns = [
    path('', views.history_list, name='list'),
]