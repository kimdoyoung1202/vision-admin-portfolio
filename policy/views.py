from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.utils import timezone
from django.contrib import messages
from django.db import transaction
from django.db.models import Max
from policy.utils_engine import send_reload_signal
import re
from policy_history.models import PolicyHistory
from .models import Policy
from ai_analysis_result.models import AiAnalysisResult
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date
from django.http import JsonResponse



def policy_list(request):
    qs = Policy.objects.filter(is_deleted=False).order_by("-create_at")

    policy_type = (request.GET.get("policy_type") or "").strip()
    policy_id   = (request.GET.get("policy_id") or "").strip()
    policy_name = (request.GET.get("policy_name") or "").strip()
    content     = (request.GET.get("content") or "").strip()
    is_active   = (request.GET.get("is_active") or "").strip()
    handling    = (request.GET.get("handling_type") or "").strip()
    create_by   = (request.GET.get("create_by") or "").strip()
    start_date  = (request.GET.get("start_date") or "").strip()
    end_date    = (request.GET.get("end_date") or "").strip()

    if policy_type in ("DOMAIN", "REGEX"):
        qs = qs.filter(policy_type=policy_type)
    if policy_id:
        qs = qs.filter(policy_id__icontains=policy_id)
    if policy_name:
        qs = qs.filter(policy_name__icontains=policy_name)
    if content:
        qs = qs.filter(content__icontains=content)
    if handling:
        qs = qs.filter(handling_type=handling)
    if create_by:
        qs = qs.filter(create_by__icontains=create_by)

    if is_active == "true":
        qs = qs.filter(is_active=True)
    elif is_active == "false":
        qs = qs.filter(is_active=False)

    sd = parse_date(start_date) if start_date else None
    ed = parse_date(end_date) if end_date else None
    if sd:
        qs = qs.filter(create_at__date__gte=sd)
    if ed:
        qs = qs.filter(create_at__date__lte=ed)

    paginator = Paginator(qs, 11)  # ✅ 10개 고정
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

    if request.GET.get("partial") == "1":
        return render(request, "policy/policy_list_partial.html", {
            "page_obj": page_obj,
            "filters": filters,
        })

    return render(request, "policy/policy_list.html", {
        "page_obj": page_obj,
        "filters": filters,
    })


@require_POST
def policy_delete(request, policy_id):
    policy = get_object_or_404(Policy, policy_id=policy_id, is_deleted=False)

    # 1) DB 처리 (삭제 + 히스토리) => 무조건 끝내기
    with transaction.atomic():
        PolicyHistory.objects.create(
            policy_id=policy.policy_id,
            policy_type=policy.policy_type,
            policy_name=policy.policy_name,
            content=policy.content,
            description=getattr(policy, "description", "") or "",
            handling_type=policy.handling_type,
            is_active=policy.is_active,
            create_by=getattr(policy, "create_by", None),
            create_at=getattr(policy, "create_at", None),
            delete_by=(request.user.username if request.user.is_authenticated else "system"),
            delete_at=timezone.now(),
        )

        policy.is_deleted = True
        policy.is_active = False
        policy.save(update_fields=["is_deleted", "is_active"])

    
    try:
        send_reload_signal("reload")
        messages.success(request, "삭제 완료 (엔진 반영 완료)")
    except Exception as e:
        messages.warning(request, f"삭제 완료 (엔진 반영 실패: {e})")

    return redirect("policy:list")

def policy_add(request):
    ai_id = request.GET.get("ai_id") or request.POST.get("ai_id")
    return_to = request.GET.get("return_to") or request.POST.get("return_to")

    ai_row = None
    if ai_id and str(ai_id).isdigit():
        ai_row = AiAnalysisResult.objects.filter(id=int(ai_id)).first()

    if request.method == "POST":
        policy_type   = (request.POST.get("policy_type") or "").strip()
        content       = (request.POST.get("content") or "").strip()
        policy_name   = (request.POST.get("policy_name") or "").strip()
        description   = (request.POST.get("description") or "").strip()
        handling_type = (request.POST.get("handling_type") or "").strip()
        is_active_raw = (request.POST.get("is_active") or "false").strip().lower()
        is_active = (is_active_raw == "true")

        errors = []
        if not policy_type:
            errors.append("정책 타입을 선택하세요.")
        if not content:
            errors.append("정책 URL/표현식을 입력하세요.")
        if not policy_name:
            errors.append("정책 이름을 입력하세요.")
        if handling_type not in ("block", "log"):
            errors.append("처리 유형이 올바르지 않습니다.")
        if content and Policy.objects.filter(content=content, is_deleted=False).exists():
            errors.append("이미 동일한 정책(content)이 존재합니다.")

        if errors:
            context = {
                "errors": errors,
                "ai_id": ai_id,
                "return_to": return_to,
                "initial_content": ai_row.request_url if ai_row else "",
                "initial_domain": ai_row.domain if ai_row else "",
                "form": {
                    "policy_type": {"value": policy_type},
                    "content": {"value": content},
                    "policy_name": {"value": policy_name},
                    "description": {"value": description},
                    "handling_type": {"value": handling_type},
                    "is_active": {"value": is_active_raw},
                }
            }
            return render(request, "policy/policy_add.html", context)

        # ✅ DB 처리만 atomic에서 끝내고, 그 밖에서 redirect/엔진호출
        created_policy_id = None
        with transaction.atomic():
            new_policy_id = generate_policy_id(policy_type)
            created_policy_id = new_policy_id

            data = {
                "policy_id": new_policy_id,
                "policy_type": policy_type,
                "content": content,
                "policy_name": policy_name,
                "description": description,
                "handling_type": handling_type,
                "is_active": is_active,
            }

            if hasattr(Policy, "create_by"):
                data["create_by"] = request.user.username if request.user.is_authenticated else "system"
            if hasattr(Policy, "create_at"):
                data["create_at"] = timezone.now()

            Policy.objects.create(**data)

            if ai_id and ai_row:
                ai_row.is_checked = True
                ai_row.checked_result = "ADD"
                ai_row.policy_type = policy_type
                ai_row.applied_at = timezone.now()
                ai_row.admin = request.user.username if request.user.is_authenticated else "system"
                ai_row.save(update_fields=["is_checked", "checked_result", "policy_type", "applied_at", "admin"])

        # ✅ 엔진 반영은 atomic 밖 + 실패해도 add는 성공
        try:
            send_reload_signal("reload")
            messages.success(request, "정책이 추가되었습니다. (엔진 반영 완료)")
        except Exception as e:
            messages.warning(request, f"정책이 추가되었습니다. (엔진 반영 실패: {e})")

        # ✅ return_to 정리
        rt = (return_to or "").strip()
        if rt.lower() in ("none", "null", "undefined"):
            rt = ""

        if rt:
            return redirect(rt)

        if ai_id and str(ai_id).isdigit():
            return redirect(f"/ai/records/?highlight_id={int(ai_id)}")

        return redirect("policy:list")

    return render(
        request,
        "policy/policy_add.html",
        {
            "ai_id": ai_id,
            "return_to": return_to,
            "initial_content": ai_row.request_url if ai_row else "",
            "initial_domain": ai_row.domain if ai_row else "",
        },
    )



def generate_policy_id(policy_type):
    # policy_type은 DB 저장값: DOMAIN / REGEX
    if policy_type == "DOMAIN":
        prefix = "DO"
    elif policy_type == "REGEX":
        prefix = "REG"
    else:
        raise ValueError(f"Invalid policy_type: {policy_type}")

    last = (
        Policy.objects
        .filter(policy_id__startswith=f"{prefix}-")
        .order_by("-policy_id")
        .first()
    )

    if not last or not last.policy_id:
        return f"{prefix}-001"

    last_number = int(last.policy_id.split("-")[1])
    return f"{prefix}-{last_number + 1:03d}"



@require_POST
def policy_update(request, policy_id):
    # POST 값
    is_active_raw = (request.POST.get("is_active") or "").strip().lower()
    handling_type = (request.POST.get("handling_type") or "").strip().lower()
    next_url = (request.POST.get("next") or "").strip()

    # 검증
    errors = []
    if is_active_raw not in ("true", "false"):
        errors.append("정책 적용 여부 값이 올바르지 않습니다.")
    if handling_type not in ("block", "log"):
        errors.append("처리 유형 값이 올바르지 않습니다.")

    if errors:
        for e in errors:
            messages.error(request, e)
        return redirect(next_url or "policy:list")

    is_active = (is_active_raw == "true")

    # 1) DB 업데이트는 트랜잭션으로 확실히 끝내기
    with transaction.atomic():
        updated = Policy.objects.filter(policy_id=policy_id, is_deleted=False).update(
            is_active=is_active,
            handling_type=handling_type,
        )
        if updated == 0:
            messages.error(request, "정책을 찾을 수 없습니다.")
            return redirect(next_url or "policy:list")

    # 2) 엔진 반영은 트랜잭션 밖에서 + 실패해도 뷰는 정상 종료
    try:
        send_reload_signal("reload")
        messages.success(request, "정책이 업데이트되었습니다. (엔진 반영 완료)")
    except Exception as e:
        messages.warning(request, f"정책은 업데이트되었습니다. (엔진 반영 실패: {e})")

    return redirect(next_url or "policy:list")