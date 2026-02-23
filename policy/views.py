from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.utils import timezone
from django.contrib import messages
from django.db import transaction
from django.db.models import Max
import re
from policy_history.models import PolicyHistory
from .models import Policy
from ai_analysis_result.models import AiAnalysisResult



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

    with transaction.atomic():
        # 1) History에 스냅샷 저장 (필드명은 너 DB 기준: delete_at / delete_by)
        PolicyHistory.objects.create(
            policy_id=policy.policy_id,
            policy_type=policy.policy_type,
            policy_name=policy.policy_name,
            content=policy.content,
            description=getattr(policy, "description", ""),
            handling_type=policy.handling_type,
            is_active=policy.is_active,
            create_by=getattr(policy, "create_by", None),
            create_at=getattr(policy, "create_at", None),
            delete_by=(request.user.username if request.user.is_authenticated else "system"),
            delete_at=timezone.now(),
        )

        # 2) 원본 Policy 삭제 (물리삭제)
        policy.delete()


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
        is_active_raw = (request.POST.get("is_active") or "false").strip()

        is_active = True if is_active_raw == "true" else False

        errors = []
        if not policy_type:
            errors.append("정책 타입을 선택하세요.")
        if not content:
            errors.append("정책 URL/표현식을 입력하세요.")
        if not policy_name:
            errors.append("정책 이름을 입력하세요.")
        if handling_type not in ("block", "log"):
            errors.append("처리 유형이 올바르지 않습니다.")
        
        if content and Policy.objects.filter(content=content).exists():
            errors.append("이미 동일한 정책(content)이 존재합니다.")

        if errors:
            context = {
                "errors": errors,
                "ai_id": ai_id,                  
                "return_to": return_to,            
                "initial_content": ai_row.request_url if ai_row else "", 
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

        # ✅ 여기서 policy_id 자동 생성
        with transaction.atomic():
            new_policy_id = generate_policy_id(policy_type)

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
                ai_row.policy_type = policy_type          # DOMAIN / REGEX
                ai_row.applied_at = timezone.now()         # 추가 성공 시점
                ai_row.admin = request.user.username if request.user.is_authenticated else "system"
                ai_row.save(update_fields=["is_checked", "checked_result", "policy_type", "applied_at", "admin"])
        
            return_to = request.GET.get("return_to") or request.POST.get("return_to")

            # ✅ return_to 정리: None/빈값/"None"/"null" 같은 값 방지
            rt = (return_to or "").strip()
            if rt.lower() in ("none", "null", "undefined"):
                rt = ""

            # ✅ 안전 redirect 우선순위
            if rt:
                return redirect(rt)

            # ai_id가 숫자일 때만 highlight로
            if ai_id and str(ai_id).isdigit():
                return redirect(f"/ai/records/?highlight_id={int(ai_id)}")

            return redirect("policy:list")
        
    return render(request, "policy/policy_add.html", {"ai_id": ai_id, "return_to": return_to, "initial_content": ai_row.request_url if ai_row else "",})



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
        # 메시지 쓰고 싶으면 (선택)
        for e in errors:
            messages.error(request, e)
        return redirect(next_url or "policy:list")

    is_active = True if is_active_raw == "true" else False

    # ✅ managed=False라도 update는 가능
    updated = Policy.objects.filter(policy_id=policy_id).update(
        is_active=is_active,
        handling_type=handling_type,
    )

    if updated == 0:
        messages.error(request, "정책을 찾을 수 없습니다.")
        return redirect(next_url or "policy:list")

    messages.success(request, "정책이 업데이트되었습니다.")
    return redirect(next_url or "policy:list")
