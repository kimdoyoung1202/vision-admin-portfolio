from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils.dateparse import parse_date

from .models import PolicyUpdateHistory
from policy.models import Policy


def _txt(v):
    """
    None 값을 빈 문자열로 바꾸고,
    나머지는 문자열로 변환 후 좌우 공백 제거
    """
    return "" if v is None else str(v).strip()


def _active_text(v):
    """
    활성 여부(Boolean)를 화면용 한글 텍스트로 변환
    """
    return "적용" if bool(v) else "미적용"


def _normalize_active_param(v):
    """
    검색 파라미터로 들어온 활성 여부 값을 정규화
    - 활성 관련 값이면 True
    - 비활성 관련 값이면 False
    - 그 외는 None
    """
    v = (v or "").strip().lower()

    if v in ("1", "true", "y", "yes", "active", "적용"):
        return True

    if v in ("0", "false", "n", "no", "inactive", "미적용"):
        return False

    return None


def _changed_fields(before_obj, after_obj):
    """
    수정 전/후 객체를 비교해서
    실제 변경된 필드명만 리스트로 반환
    """
    fields = []

    if _txt(before_obj.policy_type) != _txt(after_obj.policy_type):
        fields.append("정책 타입")

    if _txt(before_obj.policy_name) != _txt(after_obj.policy_name):
        fields.append("정책 이름")

    if _txt(before_obj.content) != _txt(after_obj.content):
        fields.append("URL")

    if _txt(before_obj.description) != _txt(after_obj.description):
        fields.append("정책 설명")

    if _txt(before_obj.handling_type) != _txt(after_obj.handling_type):
        fields.append("처리 유형")

    if bool(before_obj.is_active) != bool(after_obj.is_active):
        fields.append("적용 여부")

    return fields


def _build_after_map(rows):
    """
    같은 policy_id 기준으로 각 history row의 '수정 후 상태(after)'를 매핑

    규칙:
    - 더 최근 history row가 있으면 그 row를 현재 row의 after 로 사용
    - 더 최근 history row가 없으면 현재 Policy 테이블 값을 after 로 사용
    """
    policy_ids = list({row.policy_id for row in rows if row.policy_id is not None})

    current_policies = {
        p.id: p for p in Policy.objects.filter(id__in=policy_ids)
    }

    grouped = {}
    for row in rows:
        grouped.setdefault(row.policy_id, []).append(row)

    after_map = {}

    for policy_id, items in grouped.items():
        # 최신 수정 이력이 앞에 오도록 정렬
        items = sorted(items, key=lambda x: (x.update_at, x.id), reverse=True)

        for idx, row in enumerate(items):
            if idx == 0:
                # 가장 최신 이력의 after 는 현재 Policy 테이블 상태
                after_obj = current_policies.get(policy_id)
            else:
                # 그 외에는 바로 이전(더 최신) history row를 after 로 사용
                after_obj = items[idx - 1]

            after_map[row.id] = after_obj

    return after_map


def _build_changed_rows(before_obj, after_obj):
    """
    수정 전/후 차이를 모달 상세 표시용 구조로 생성
    [
        {"label": "...", "before": "...", "after": "..."},
        ...
    ]
    """
    rows = []

    def add_row(label, before_val, after_val):
        before_txt = "-" if _txt(before_val) == "" else str(before_val)
        after_txt = "-" if _txt(after_val) == "" else str(after_val)

        if before_txt != after_txt:
            rows.append({
                "label": label,
                "before": before_txt,
                "after": after_txt,
            })

    add_row("정책 타입", before_obj.policy_type, after_obj.policy_type)
    add_row("정책 이름", before_obj.policy_name, after_obj.policy_name)
    add_row("URL", before_obj.content, after_obj.content)
    add_row("정책 설명", before_obj.description, after_obj.description)
    add_row("처리 유형", before_obj.handling_type, after_obj.handling_type)
    add_row("적용 여부", _active_text(before_obj.is_active), _active_text(after_obj.is_active))

    return rows


def history_list(request):
    """
    정책 수정 이력 목록 조회
    - 검색 조건 적용
    - 수정 전/후 비교 데이터 생성
    - 페이지네이션 처리
    - 일반 요청 / partial 요청 템플릿 분기
    """
    qs = PolicyUpdateHistory.objects.all().order_by("-update_at", "-id")

    # 검색 파라미터 수집
    policy_type = (request.GET.get("policy_type") or "").strip().upper()
    policy_name = (request.GET.get("policy_name") or "").strip()
    policy_id = (request.GET.get("policy_id") or "").strip()
    content = (request.GET.get("content") or "").strip()
    handling_type = (request.GET.get("handling_type") or "").strip().lower()
    is_active = (request.GET.get("is_active") or "").strip()
    update_by = (request.GET.get("update_by") or "").strip()
    start_date = (request.GET.get("start_date") or "").strip()
    end_date = (request.GET.get("end_date") or "").strip()

    # 정책 타입 필터
    if policy_type in ("DOMAIN", "REGEX"):
        qs = qs.filter(policy_type=policy_type)

    # 정책 이름 필터
    if policy_name:
        qs = qs.filter(policy_name__icontains=policy_name)

    # 정책 ID 필터
    if policy_id:
        if policy_id.isdigit():
            qs = qs.filter(policy_id=int(policy_id))
        else:
            qs = qs.none()

    # URL/표현식 필터
    if content:
        qs = qs.filter(content__icontains=content)

    # 처리 유형 필터
    if handling_type in ("block", "log"):
        qs = qs.filter(handling_type__iexact=handling_type)

    # 활성 여부 필터
    active_value = _normalize_active_param(is_active)
    if active_value is not None:
        qs = qs.filter(is_active=active_value)

    # 수정자 필터
    if update_by:
        qs = qs.filter(update_by__icontains=update_by)

    # 날짜 필터
    sd = parse_date(start_date) if start_date else None
    ed = parse_date(end_date) if end_date else None

    if sd:
        qs = qs.filter(update_at__date__gte=sd)

    if ed:
        qs = qs.filter(update_at__date__lte=ed)

    # queryset 평가 후, 각 row별 after 상태 계산
    rows = list(qs)
    after_map = _build_after_map(rows)

    enriched = []

    for row in rows:
        after_obj = after_map.get(row.id)
        if not after_obj:
            continue

        # 변경된 필드명 목록
        changed = _changed_fields(row, after_obj)

        # 변경 상세(before / after)
        changed_rows = _build_changed_rows(row, after_obj)

        row.changed_fields = changed
        row.changed_rows = changed_rows
        row.changed_fields_text = ", ".join(changed) if changed else "변경 없음"

        # 모달 상단 표시용 데이터
        row.modal_policy_id = row.policy_id
        row.modal_policy_type = row.policy_type or "-"
        row.modal_policy_name = row.policy_name or "-"
        row.modal_content = row.content or "-"
        row.modal_handling_type = row.handling_type or "-"
        row.modal_is_active_text = _active_text(row.is_active)
        row.modal_description = row.description or "-"
        row.modal_update_by = row.update_by or "-"
        row.modal_update_at = row.update_at

        # before 값
        row.before_policy_type = row.policy_type or ""
        row.before_policy_name = row.policy_name or ""
        row.before_content = row.content or ""
        row.before_description = row.description or ""
        row.before_handling_type = row.handling_type or ""
        row.before_is_active = row.is_active
        row.before_is_active_text = _active_text(row.is_active)

        # after 값
        row.after_policy_type = after_obj.policy_type or ""
        row.after_policy_name = after_obj.policy_name or ""
        row.after_content = after_obj.content or ""
        row.after_description = after_obj.description or ""
        row.after_handling_type = after_obj.handling_type or ""
        row.after_is_active = after_obj.is_active
        row.after_is_active_text = _active_text(after_obj.is_active)

        # 리스트 표시용 활성 상태 텍스트
        row.is_active_text = _active_text(row.is_active)

        enriched.append(row)

    # 페이지네이션
    paginator = Paginator(enriched, 15)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    # 템플릿에서 검색값 유지용
    filters = {
        "policy_type": policy_type,
        "policy_name": policy_name,
        "policy_id": policy_id,
        "content": content,
        "handling_type": handling_type,
        "is_active": is_active,
        "update_by": update_by,
        "start_date": start_date,
        "end_date": end_date,
    }

    context = {
        "page_obj": page_obj,
        "filters": filters,
        "active_group": "policy",
        "active_menu": "policy_update_history",
    }

    # partial 요청이면 목록 영역만 반환
    if request.GET.get("partial") == "1":
        return render(request, "policy_update_history/history_list_partial.html", context)

    # 일반 요청이면 전체 페이지 반환
    return render(request, "policy_update_history/history_list.html", context)