from django.urls import path
from .views import dashboard_view
from .views_api import kpis_api, timeseries_api, top_domains_api, top_regex_api, top_ips_api

app_name = "dashboard"

urlpatterns = [
    path("", dashboard_view, name="home"),
    path("api/kpis/", kpis_api, name="kpis_api"),
    path("api/timeseries/", timeseries_api, name="api_timeseries"),
    path("api/top-domains/", top_domains_api, name="api_top_domains"),
    path("api/top-regex/", top_regex_api, name="api_top_regex"),
    path("api/top-ips/", top_ips_api, name="api_top_ips"),
]