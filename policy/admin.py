from django.contrib import admin
from .models import Policy


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = (
        "policy_name",
        "policy_type",
        "content",
        "is_active",
        "handling_type",
        "create_by",
        "create_at",
        "description",
    )

    search_fields = (
        "policy_name",
        "content",
        "create_by",
    )

    list_filter = (
        "policy_type",
        "is_active",
        "handling_type",
    )

    ordering = ("-create_at",)

    list_editable = (
        "is_active",
        "handling_type",
    )

    list_per_page = 30