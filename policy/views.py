from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from .models import Policy


def policy_list(request):
    qs = Policy.objects.all().order_by("-create_at")  # ✅ 필터 없으면 전체가 그대로 나옴

    # ✅ 필터값
    policy_type   = request.GET.get("policy_type", "")      # domain / regex / ''
    policy_name   = request.GET.get("policy_name", "").strip()
    content       = request.GET.get("content", "").strip()
    is_active     = request.GET.get("is_active", "")        # true / false / ''
    handling_type = request.GET.get("handling_type", "")    # block / log / ''
    create_by     = request.GET.get("create_by", "").strip()
    start_date    = request.GET.get("start_date", "")       # YYYY-MM-DD
    end_date      = request.GET.get("end_date", "")         # YYYY-MM-DD

    # ✅ 필터 적용
    if policy_type:
        qs = qs.filter(policy_type=policy_type)

    if policy_name:
        qs = qs.filter(policy_name__icontains=policy_name) #i: 대소문자 무시 / contains : 포함 검색

    if content:
        qs = qs.filter(content__icontains=content)

    if handling_type:
        qs = qs.filter(handling_type=handling_type)

    if create_by:
        qs = qs.filter(create_by__icontains=create_by)

    if is_active == "true":
        qs = qs.filter(is_active=True)
    elif is_active == "false":
        qs = qs.filter(is_active=False)

    # ✅ 기간 검색 (create_at이 DateTimeField라 date로 비교)
    if start_date:
        qs = qs.filter(create_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(create_at__date__lte=end_date)

    # ✅ 페이지네이션: 30개씩
    paginator = Paginator(qs, 30)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "filters": {
            "policy_type": policy_type,
            "policy_name": policy_name,
            "content": content,
            "is_active": is_active,
            "handling_type": handling_type,
            "create_by": create_by,
            "start_date": start_date,
            "end_date": end_date,
        }
    }
    return render(request, "policy/policy_list.html", context)


@require_POST
def policy_delete(request, policy_id):
    policy = get_object_or_404(Policy, policy_id=policy_id)
    policy.delete()
    # ✅ 삭제 후, 기존 필터 유지하면서 목록으로 가고 싶으면 next 사용도 가능(나중에)
    return redirect("policy:list")

def policy_add(request):
    return HttpResponse("policy_add (임시 페이지)")

def policy_history(request):
    return HttpResponse("policy_history (임시 페이지)")
