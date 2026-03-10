from django.contrib import admin
from .models import PolicyDeleteHistory


@admin.register(PolicyDeleteHistory)
class PolicyDeleteHistoryAdmin(admin.ModelAdmin):

    list_display = (
        "policy_name",
        "policy_type",
        "content",
        "description",
        "handling_type",
        "is_active",
        "create_by",
        "create_at",
        "delete_by",
        "delete_at",
    )

    search_fields = (
        "policy_name",
        "content",
        "delete_by",
    )

    list_filter = (
        "is_active",
        "handling_type",
    )

    ordering = ("-delete_at",)
    list_per_page = 30