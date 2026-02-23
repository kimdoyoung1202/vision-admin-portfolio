from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import transaction

from policy.models import Policy
from .models import PolicyHistory

# Create your views here.

from django.core.paginator import Paginator
from django.shortcuts import render
from .models import PolicyHistory

def policy_history_list(request):
    qs = PolicyHistory.objects.all().order_by("-delete_at")  # ✅ DB 필드: delete_at

    # ✅ 필터값 (템플릿 input name과 맞춰서 받기)
    policy_type   = request.GET.get("policy_type", "")
    policy_id     = request.GET.get("policy_id", "").strip()
    policy_name   = request.GET.get("policy_name", "").strip()
    content       = request.GET.get("content", "").strip()
    is_active     = request.GET.get("is_active", "")
    handling_type = request.GET.get("handling_type", "")
    deleted_by    = request.GET.get("deleted_by", "").strip()  # ✅ 여기 중요 (deleted_by로 받기)
    start_date    = request.GET.get("start_date", "")
    end_date      = request.GET.get("end_date", "")

    # ✅ 필터 적용
    if policy_type:
        qs = qs.filter(policy_type=policy_type)

    if policy_id:
        qs = qs.filter(policy_id__icontains=policy_id)

    if policy_name:
        qs = qs.filter(policy_name__icontains=policy_name)

    if content:
        qs = qs.filter(content__icontains=content)

    if handling_type:
        qs = qs.filter(handling_type=handling_type)

    if deleted_by:
        qs = qs.filter(delete_by__icontains=deleted_by)  # ✅ DB 필드: delete_by

    if is_active == "true":
        qs = qs.filter(is_active=True)
    elif is_active == "false":
        qs = qs.filter(is_active=False)

    # ✅ 삭제시간 기간 검색 (DB 필드: delete_at)
    if start_date:
        qs = qs.filter(delete_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(delete_at__date__lte=end_date)

    # ✅ 페이지네이션: 30개씩
    paginator = Paginator(qs, 30)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "filters": {
            "policy_type": policy_type,
            "policy_id": policy_id,
            "policy_name": policy_name,
            "content": content,
            "is_active": is_active,
            "handling_type": handling_type,
            "deleted_by": deleted_by,   # ✅ 템플릿에서 filters.deleted_by 로 계속 쓰면 됨
            "start_date": start_date,
            "end_date": end_date,
        }
    }
    return render(request, "policy_history/policy_history.html", context)


@require_POST
def policy_history_restore(request, policy_id):
    h = get_object_or_404(PolicyHistory, policy_id=policy_id)

    with transaction.atomic():
        # Policy에 복원(있으면 업데이트, 없으면 생성)
        Policy.objects.update_or_create(
            policy_id=h.policy_id,
            defaults={
                "policy_type": h.policy_type,
                "policy_name": h.policy_name,
                "content": h.content,
                "description": getattr(h, "description", ""),
                "handling_type": h.handling_type,
                "is_active": True,  # 복구니까 활성으로
                "create_by": (request.user.username if request.user.is_authenticated else "system"),
                "create_at": timezone.now(),
            }
        )

        
        h.delete()

    return redirect("policy_history:list")