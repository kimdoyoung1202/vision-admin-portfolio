from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.utils.dateparse import parse_datetime
from django.http import JsonResponse
from django.urls import reverse

from policy.utils_engine import send_reload_signal
from policy_delete_history.models import PolicyDeleteHistory
from policy_update_history.models import PolicyUpdateHistory
from .models import Policy
from ai_analysis_result.models import AiAnalysisResult


# 정책 수정 이력을 저장하는 공통 함수
# 수정 전 상태를 policy_update_history 테이블에 백업한다.
def save_policy_update_history(policy, request):
    PolicyUpdateHistory.objects.create(
        policy_id=policy.id,
        policy_name=policy.policy_name,
        policy_type=policy.policy_type,
        content=policy.content,
        description=policy.description,
        handling_type=policy.handling_type,
        is_active=policy.is_active,
        create_by=policy.create_by,
        create_at=policy.create_at,
        update_by=(request.user.username if request.user.is_authenticated else "system"),
        update_at=timezone.now(),
    )


# 정책 추가 화면용 컨텍스트를 만드는 공통 함수
# 에러 재렌더링 시 입력값과 AI 연계값을 함께 넘긴다.
def build_policy_add_context(ai_id, return_to, ai_row=None, errors=None, form=None):
    return {
        "errors": errors or [],
        "ai_id": ai_id,
        "return_to": return_to,
        "initial_content": ai_row.request_url if ai_row else "",
        "initial_domain": ai_row.domain if ai_row else "",
        "form": form or {},
        "active_group": "policy",
        "active_menu": "policy_add",
    }


# 내부 경로만 리다이렉트 대상으로 허용한다.
def is_safe_internal_path(path):
    return bool(path) and path.startswith("/") and not path.startswith("//")


# 정책 목록 페이지
# 필터, 날짜 검색, 페이지네이션, 부분 렌더링을 처리한다.
def policy_list(request):
    # 기본 목록 조회
    qs = Policy.objects.all().order_by("-create_at", "-id")

    # 필터 값 수집
    policy_type = (request.GET.get("policy_type") or "").strip().upper()
    policy_id = (request.GET.get("policy_id") or "").strip()
    policy_name = (request.GET.get("policy_name") or "").strip()
    content = (request.GET.get("content") or "").strip()
    is_active = (request.GET.get("is_active") or "").strip().lower()
    handling = (request.GET.get("handling_type") or "").strip().lower()
    create_by = (request.GET.get("create_by") or "").strip()
    start_date = (request.GET.get("start_date") or "").strip()
    end_date = (request.GET.get("end_date") or "").strip()

    # 검색 조건 적용
    if policy_type in ("DOMAIN", "REGEX"):
        qs = qs.filter(policy_type=policy_type)

    if policy_id:
        if policy_id.isdigit():
            qs = qs.filter(id=int(policy_id))
        else:
            qs = qs.none()

    if policy_name:
        qs = qs.filter(policy_name__icontains=policy_name)

    if content:
        qs = qs.filter(content__icontains=content)

    if handling in ("block", "log"):
        qs = qs.filter(handling_type=handling)

    if create_by:
        qs = qs.filter(create_by__icontains=create_by)

    if is_active == "true":
        qs = qs.filter(is_active=True)
    elif is_active == "false":
        qs = qs.filter(is_active=False)

    # 날짜 범위 필터
    start_dt = parse_datetime(start_date) if start_date else None
    end_dt = parse_datetime(end_date) if end_date else None

    if start_dt and timezone.is_naive(start_dt):
        start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())

    if end_dt and timezone.is_naive(end_dt):
        end_dt = timezone.make_aware(end_dt, timezone.get_current_timezone())

    if start_dt:
        qs = qs.filter(create_at__gte=start_dt)

    if end_dt:
        qs = qs.filter(create_at__lte=end_dt)

    # 페이지네이션
    paginator = Paginator(qs, 12)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    filters = {
        "policy_type": policy_type,
        "policy_id": policy_id,
        "policy_name": policy_name,
        "content": content,
        "is_active": is_active,
        "handling_type": handling,
        "create_by": create_by,
        "start_date": start_date,
        "end_date": end_date,
    }

    context = {
        "page_obj": page_obj,
        "filters": filters,
        "active_group": "policy",
        "active_menu": "policy_list",
    }

    # AJAX 요청이면 목록 부분만 반환
    if (
        request.GET.get("partial") == "1"
        and request.headers.get("X-Requested-With") == "XMLHttpRequest"
    ):
        return render(request, "policy/policy_list_partial.html", context)

    return render(request, "policy/policy_list.html", context)


# 정책 삭제 처리
# 삭제 전 데이터를 PolicyDeleteHistory에 저장한 뒤 실제 정책을 삭제한다.
@require_POST
def policy_delete(request, policy_id):
    policy = get_object_or_404(Policy, id=policy_id)

    with transaction.atomic():
        PolicyDeleteHistory.objects.create(
            policy_type=policy.policy_type,
            policy_name=policy.policy_name,
            content=policy.content,
            description=policy.description or "",
            handling_type=policy.handling_type,
            is_active=policy.is_active,
            create_by=policy.create_by,
            create_at=policy.create_at,
            delete_by=(request.user.username if request.user.is_authenticated else "system"),
            delete_at=timezone.now(),
        )
        policy.delete()

    try:
        send_reload_signal("reload")
        messages.success(request, "삭제 완료 (엔진 반영 완료)")
    except Exception as e:
        messages.warning(request, f"삭제 완료 (엔진 반영 실패: {e})")

    return redirect("policy:list")


# 정책 추가 페이지
# 신규 정책 저장과 AI 분석 결과 연계를 처리한다.
def policy_add(request):
    ai_id = request.GET.get("ai_id") or request.POST.get("ai_id")
    return_to = request.GET.get("return_to") or request.POST.get("return_to")

    ai_row = None
    if ai_id and str(ai_id).isdigit():
        ai_row = AiAnalysisResult.objects.filter(id=int(ai_id)).first()

    if request.method == "POST":
        # 입력값 수집
        policy_type = (request.POST.get("policy_type") or "").strip().upper()
        content = (request.POST.get("content") or "").strip()
        policy_name = (request.POST.get("policy_name") or "").strip()
        description = (request.POST.get("description") or "").strip()
        handling_type = (request.POST.get("handling_type") or "").strip().lower()
        is_active_raw = (request.POST.get("is_active") or "false").strip().lower()
        is_active = (is_active_raw == "true")

        form_data = {
            "policy_type": {"value": policy_type},
            "content": {"value": content},
            "policy_name": {"value": policy_name},
            "description": {"value": description},
            "handling_type": {"value": handling_type},
            "is_active": {"value": is_active_raw},
        }

        # 입력값 검증
        errors = []

        if policy_type not in ("DOMAIN", "REGEX"):
            errors.append("정책 타입을 선택하세요.")

        if not content:
            errors.append("정책 URL/표현식을 입력하세요.")

        if not policy_name:
            errors.append("정책 이름을 입력하세요.")

        if handling_type not in ("block", "log"):
            errors.append("처리 유형이 올바르지 않습니다.")

        if content and Policy.objects.filter(content=content).exists():
            errors.append("동일한 도메인/패턴이 이미 등록되어 있습니다.")

        if errors:
            return render(
                request,
                "policy/policy_add.html",
                build_policy_add_context(
                    ai_id=ai_id,
                    return_to=return_to,
                    ai_row=ai_row,
                    errors=errors,
                    form=form_data,
                ),
            )

        try:
            with transaction.atomic():
                now = timezone.now()
                admin_name = request.user.username if request.user.is_authenticated else "system"

                Policy.objects.create(
                    policy_type=policy_type,
                    content=content,
                    policy_name=policy_name,
                    description=description,
                    handling_type=handling_type,
                    is_active=is_active,
                    create_by=admin_name,
                    create_at=now,
                )

                # DOMAIN 정책은 같은 도메인 로그를 일괄 반영한다.
                if policy_type == "DOMAIN":
                    AiAnalysisResult.objects.filter(
                        domain__iexact=content
                    ).update(
                        is_checked=True,
                        checked_result="ADD",
                        policy_type="DOMAIN",
                        applied_at=now,
                        admin=admin_name,
                    )

                # REGEX 정책은 선택한 AI 로그 1건만 반영한다.
                elif policy_type == "REGEX" and ai_id and ai_row:
                    ai_row.is_checked = True
                    ai_row.checked_result = "ADD"
                    ai_row.policy_type = "REGEX"
                    ai_row.applied_at = now
                    ai_row.admin = admin_name
                    ai_row.save(update_fields=[
                        "is_checked",
                        "checked_result",
                        "policy_type",
                        "applied_at",
                        "admin",
                    ])

        except IntegrityError:
            return render(
                request,
                "policy/policy_add.html",
                build_policy_add_context(
                    ai_id=ai_id,
                    return_to=return_to,
                    ai_row=ai_row,
                    errors=["동일한 도메인/패턴이 이미 등록되어 있습니다."],
                    form=form_data,
                ),
            )

        try:
            send_reload_signal("reload")
            messages.success(request, "정책이 추가되었습니다. (엔진 반영 완료)")
        except Exception as e:
            messages.warning(request, f"정책은 추가되었지만 엔진 반영은 실패했습니다. ({e})")

        rt = (return_to or "").strip()
        if rt.lower() in ("none", "null", "undefined"):
            rt = ""

        if is_safe_internal_path(rt):
            return redirect(rt)

        if ai_id and str(ai_id).isdigit():
            return redirect(f"/ai/records/?highlight_id={int(ai_id)}")

        return redirect("policy:list")

    return render(
        request,
        "policy/policy_add.html",
        build_policy_add_context(
            ai_id=ai_id,
            return_to=return_to,
            ai_row=ai_row,
        ),
    )


# 정책 간단 수정 처리
# is_active와 handling_type 값을 수정하고 변경 이력을 남긴다.
@require_POST
def policy_update(request, policy_id):
    # 입력값 수집
    is_active_raw = (request.POST.get("is_active") or "").strip().lower()
    handling_type = (request.POST.get("handling_type") or "").strip().lower()
    next_url = (request.POST.get("next") or "").strip()

    # 입력값 검증
    errors = []

    if is_active_raw not in ("true", "false"):
        errors.append("정책 적용 여부 값이 올바르지 않습니다.")

    if handling_type not in ("block", "log"):
        errors.append("처리 유형 값이 올바르지 않습니다.")

    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect(next_url or "policy:list")

    is_active = (is_active_raw == "true")
    policy = get_object_or_404(Policy, id=policy_id)

    changed = (
        policy.is_active != is_active or
        policy.handling_type != handling_type
    )

    with transaction.atomic():
        if changed:
            save_policy_update_history(policy, request)

            policy.is_active = is_active
            policy.handling_type = handling_type
            policy.save(update_fields=["is_active", "handling_type"])

    try:
        send_reload_signal("reload")
        messages.success(request, "정책이 업데이트되었습니다. (엔진 반영 완료)")
    except Exception as e:
        messages.warning(request, f"정책은 업데이트되었습니다. (엔진 반영 실패: {e})")

    return redirect(next_url or "policy:list")


# 정책 전체 수정 AJAX
# 정책 기본 정보와 상태값을 수정하고 JSON으로 결과를 반환한다.
@require_POST
def policy_edit_ajax(request, policy_id):
    policy = get_object_or_404(Policy, id=policy_id)

    # 입력값 수집
    policy_type = (request.POST.get("policy_type") or "").strip().upper()
    policy_name = (request.POST.get("policy_name") or "").strip()
    content = (request.POST.get("content") or "").strip()
    description = (request.POST.get("description") or "").strip()
    is_active_raw = (request.POST.get("is_active") or "").strip().lower()
    handling_type = (request.POST.get("handling_type") or "").strip().lower()

    # 입력값 검증
    errors = []

    if policy_type not in ("DOMAIN", "REGEX"):
        errors.append("정책 타입을 선택하세요.")

    if not policy_name:
        errors.append("정책 이름을 입력하세요.")

    if not content:
        errors.append("정책 URL/표현식을 입력하세요.")

    if is_active_raw not in ("true", "false"):
        errors.append("정책 적용 여부 값이 올바르지 않습니다.")

    if handling_type not in ("block", "log"):
        errors.append("처리 유형 값이 올바르지 않습니다.")

    dup_qs = Policy.objects.filter(content=content).exclude(id=policy_id)
    if content and dup_qs.exists():
        errors.append("동일한 도메인/패턴이 이미 등록되어 있습니다.")

    if errors:
        return JsonResponse({
            "ok": False,
            "message": errors[0],
            "errors": errors,
        }, status=400)

    is_active = (is_active_raw == "true")

    changed = any([
        policy.policy_type != policy_type,
        policy.policy_name != policy_name,
        policy.content != content,
        (policy.description or "") != description,
        policy.is_active != is_active,
        policy.handling_type != handling_type,
    ])

    with transaction.atomic():
        if changed:
            save_policy_update_history(policy, request)

            policy.policy_type = policy_type
            policy.policy_name = policy_name
            policy.content = content
            policy.description = description
            policy.is_active = is_active
            policy.handling_type = handling_type
            policy.save(update_fields=[
                "policy_type",
                "policy_name",
                "content",
                "description",
                "is_active",
                "handling_type",
            ])

    try:
        send_reload_signal("reload")
        reload_message = "정책이 수정되었습니다. (엔진 반영 완료)"
    except Exception as e:
        reload_message = f"정책은 수정되었지만 엔진 반영은 실패했습니다. ({e})"

    return JsonResponse({
        "ok": True,
        "message": reload_message,
        "item": {
            "id": policy.id,
            "policy_type": policy.policy_type,
            "policy_name": policy.policy_name,
            "content": policy.content,
            "description": policy.description or "",
            "is_active": policy.is_active,
            "handling_type": policy.handling_type,
            "create_by": policy.create_by,
            "create_at": policy.create_at.strftime("%Y-%m-%d %H:%M") if policy.create_at else "",
            "update_url": reverse("policy:update", args=[policy.id]),
            "delete_url": reverse("policy:delete", args=[policy.id]),
        }
    })