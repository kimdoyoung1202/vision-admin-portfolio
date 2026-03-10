from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils.dateparse import parse_date

from .models import PolicyUpdateHistory
from policy.models import Policy


def _txt(v):
    return "" if v is None else str(v).strip()


def _active_text(v):
    return "적용" if bool(v) else "미적용"


def _normalize_active_param(v):
    v = (v or "").strip().lower()
    if v in ("1", "true", "y", "yes", "active", "적용"):
        return True
    if v in ("0", "false", "n", "no", "inactive", "미적용"):
        return False
    return None


def _changed_fields(before_obj, after_obj):
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
    같은 policy_id 기준
    - 더 최근 history row가 있으면 그 row가 현재 row의 after
    - 없으면 현재 policy 테이블 값이 after
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
        items = sorted(items, key=lambda x: (x.update_at, x.id), reverse=True)

        for idx, row in enumerate(items):
            if idx == 0:
                after_obj = current_policies.get(policy_id)
            else:
                after_obj = items[idx - 1]

            after_map[row.id] = after_obj

    return after_map


def _build_changed_rows(before_obj, after_obj):
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
    qs = PolicyUpdateHistory.objects.all().order_by("-update_at", "-id")

    policy_type = (request.GET.get("policy_type") or "").strip().upper()
    policy_name = (request.GET.get("policy_name") or "").strip()
    policy_id = (request.GET.get("policy_id") or "").strip()
    content = (request.GET.get("content") or "").strip()
    handling_type = (request.GET.get("handling_type") or "").strip().lower()
    is_active = (request.GET.get("is_active") or "").strip()
    update_by = (request.GET.get("update_by") or "").strip()
    start_date = (request.GET.get("start_date") or "").strip()
    end_date = (request.GET.get("end_date") or "").strip()

    if policy_type in ("DOMAIN", "REGEX"):
        qs = qs.filter(policy_type=policy_type)

    if policy_name:
        qs = qs.filter(policy_name__icontains=policy_name)

    if policy_id:
        if policy_id.isdigit():
            qs = qs.filter(policy_id=int(policy_id))
        else:
            qs = qs.none()

    if content:
        qs = qs.filter(content__icontains=content)

    if handling_type in ("block", "log"):
        qs = qs.filter(handling_type__iexact=handling_type)

    active_value = _normalize_active_param(is_active)
    if active_value is not None:
        qs = qs.filter(is_active=active_value)

    if update_by:
        qs = qs.filter(update_by__icontains=update_by)

    sd = parse_date(start_date) if start_date else None
    ed = parse_date(end_date) if end_date else None

    if sd:
        qs = qs.filter(update_at__date__gte=sd)
    if ed:
        qs = qs.filter(update_at__date__lte=ed)

    rows = list(qs)
    after_map = _build_after_map(rows)

    enriched = []
    for row in rows:
        after_obj = after_map.get(row.id)
        if not after_obj:
            continue

        changed = _changed_fields(row, after_obj)
        changed_rows = _build_changed_rows(row, after_obj)

        row.changed_fields = changed
        row.changed_rows = changed_rows
        row.changed_fields_text = ", ".join(changed) if changed else "변경 없음"

        # 모달 상단 표시용
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

        # 리스트 표시용
        row.is_active_text = _active_text(row.is_active)

        enriched.append(row)

    paginator = Paginator(enriched, 12)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

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

    if request.GET.get("partial") == "1":
        return render(request, "policy_update_history/history_list_partial.html", context)

    return render(request, "policy_update_history/history_list.html", context)