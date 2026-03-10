from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import transaction
from django.contrib import messages
from django.http import JsonResponse

from policy.utils_engine import send_reload_signal
from policy.models import Policy
from .models import PolicyDeleteHistory


def policy_delete_history_list(request):
    qs = PolicyDeleteHistory.objects.all().order_by("-delete_at")

    policy_type = request.GET.get("policy_type", "")
    policy_name = request.GET.get("policy_name", "").strip()
    content = request.GET.get("content", "").strip()
    is_active = request.GET.get("is_active", "")
    handling_type = request.GET.get("handling_type", "")
    delete_by = request.GET.get("delete_by", "").strip()
    start_date = request.GET.get("start_date", "")
    end_date = request.GET.get("end_date", "")

    if policy_type:
        qs = qs.filter(policy_type=policy_type)

    if policy_name:
        qs = qs.filter(policy_name__icontains=policy_name)

    if content:
        qs = qs.filter(content__icontains=content)

    if handling_type:
        qs = qs.filter(handling_type=handling_type)

    if delete_by:
        qs = qs.filter(delete_by__icontains=delete_by)

    if is_active == "true":
        qs = qs.filter(is_active=True)
    elif is_active == "false":
        qs = qs.filter(is_active=False)

    if start_date:
        qs = qs.filter(delete_at__date__gte=start_date)

    if end_date:
        qs = qs.filter(delete_at__date__lte=end_date)

    paginator = Paginator(qs, 12)
    page_number = request.GET.get("page", "1")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "filters": {
            "policy_type": policy_type,
            "policy_name": policy_name,
            "content": content,
            "is_active": is_active,
            "handling_type": handling_type,
            "delete_by": delete_by,
            "start_date": start_date,
            "end_date": end_date,
        },
    }

    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    template = (
        "policy_delete_history/policy_delete_history_partial.html"
        if is_ajax
        else "policy_delete_history/policy_delete_history.html"
    )
    return render(request, template, context)


@require_POST
def policy_delete_history_restore(request, history_id):
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    h = get_object_or_404(PolicyDeleteHistory, id=history_id)

    try:
        with transaction.atomic():
            Policy.objects.create(
                policy_type=h.policy_type,
                policy_name=h.policy_name,
                content=h.content,
                description=h.description or "",
                handling_type=h.handling_type,
                is_active=True,
                create_by=request.user.username if request.user.is_authenticated else "system",
                create_at=timezone.now(),
            )

            h.delete()

        reload_ok = True
        reload_error = ""
        try:
            send_reload_signal("reload")
        except Exception as e:
            reload_ok = False
            reload_error = str(e)

        if is_ajax:
            return JsonResponse({
                "ok": True,
                "reload_ok": reload_ok,
                "reload_error": reload_error,
            })

        if reload_ok:
            messages.success(request, "정책이 복구되었습니다. (엔진 반영 완료)")
        else:
            messages.warning(request, f"정책은 복구되었습니다. (엔진 반영 실패: {reload_error})")

        return redirect("policy_delete_history:list")

    except Exception as e:
        if is_ajax:
            return JsonResponse({"ok": False, "error": str(e)}, status=400)
        raise