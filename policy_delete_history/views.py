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
    """
    삭제된 정책 목록 조회
    - 검색 조건을 적용해 삭제 이력을 필터링
    - 일반 요청이면 전체 페이지 템플릿 반환
    - AJAX 요청이면 목록 partial 템플릿만 반환
    """
    qs = PolicyDeleteHistory.objects.all().order_by("-delete_at")

    policy_type = request.GET.get("policy_type", "").strip()
    policy_name = request.GET.get("policy_name", "").strip()
    content = request.GET.get("content", "").strip()
    is_active = request.GET.get("is_active", "")
    handling_type = request.GET.get("handling_type", "")
    delete_by = request.GET.get("delete_by", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    # policy_type 입력값 정규화
    # 프론트에서 한글/영문 어느 쪽이 와도 DB 저장값 기준으로 변환
    policy_type_map = {
        "도메인": "DOMAIN",
        "정규표현식": "REGEX",
        "domain": "DOMAIN",
        "regex": "REGEX",
        "DOMAIN": "DOMAIN",
        "REGEX": "REGEX",
    }

    normalized_policy_type = policy_type_map.get(policy_type, policy_type)

    if normalized_policy_type:
        qs = qs.filter(policy_type=normalized_policy_type)

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

    # datetime-local(예: 2026-03-20T15:30)가 들어와도 날짜 부분만 잘라서 비교
    if start_date:
        qs = qs.filter(delete_at__date__gte=start_date[:10])

    if end_date:
        qs = qs.filter(delete_at__date__lte=end_date[:10])

    # 프론트에서 per_page를 보내면 반영, 없으면 12 기본값
    try:
        per_page = int(request.GET.get("per_page", 12))
    except ValueError:
        per_page = 12

    paginator = Paginator(qs, per_page)
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
            "per_page": per_page,
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
    """
    삭제 이력 1건을 정책 테이블로 복구
    - 복구 성공 후 삭제 이력은 제거
    - 엔진 reload 신호 전송
    - AJAX / 일반 요청 모두 처리
    """
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    history = get_object_or_404(PolicyDeleteHistory, id=history_id)

    try:
        with transaction.atomic():
            Policy.objects.create(
                policy_type=history.policy_type,
                policy_name=history.policy_name,
                content=history.content,
                description=history.description or "",
                handling_type=history.handling_type,
                is_active=True,
                create_by=request.user.username if request.user.is_authenticated else "system",
                create_at=timezone.now(),
            )

            history.delete()

        reload_ok = True
        reload_error = ""

        try:
            send_reload_signal("reload")
        except Exception as e:
            reload_ok = False
            reload_error = str(e)

        if is_ajax:
            return JsonResponse(
                {
                    "ok": True,
                    "reload_ok": reload_ok,
                    "reload_error": reload_error,
                }
            )

        if reload_ok:
            messages.success(request, "정책이 복구되었습니다. (엔진 반영 완료)")
        else:
            messages.warning(
                request,
                f"정책은 복구되었습니다. (엔진 반영 실패: {reload_error})"
            )

        return redirect("policy_delete_history:list")

    except Exception as e:
        if is_ajax:
            return JsonResponse({"ok": False, "error": str(e)}, status=400)
        raise