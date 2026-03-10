from django.contrib import admin
from .models_auth import AdminTotpDevice


@admin.register(AdminTotpDevice)
class AdminTotpDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "is_enabled", "created_at", "updated_at")
    search_fields = ("user__username",)