from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from .models import IntegratedDetectionLogs


def _exact_then_contains(qs, field_name: str, value: str):
    """
    URL/도메인 같은 필드는:
    1) exact 먼저 조회해서 있으면 exact 결과 사용
    2) 없으면 icontains로 fallback
    """
    value = (value or "").strip()
    if not value:
        return qs

    exact_filter = {f"{field_name}__exact": value}
    exact_qs = qs.filter(**exact_filter)
    if exact_qs.exists():
        return exact_qs

    contains_filter = {f"{field_name}__icontains": value}
    return qs.filter(**contains_filter)


def logs_list(request):
    qs = IntegratedDetectionLogs.objects.select_related("policy_id").all()

    # ===== filters from GET =====
    f_url_or_domain = (request.GET.get("url_domain") or "").strip()     # (1) URL/도메인 입력
    f_start_date = (request.GET.get("start_date") or "").strip()        # (2) 시작일
    f_end_date = (request.GET.get("end_date") or "").strip()            # (2) 종료일
    f_policy_keyword = (request.GET.get("policy_kw") or "").strip()     # (3) 정책 이름/ID
    f_client_ip = (request.GET.get("client_ip") or "").strip()          # (4) 사용자 IP
    f_policy_type = (request.GET.get("policy_type") or "").strip()  # (5) ALL / DOMAIN / REGEX
    f_method = (request.GET.get("method") or "").strip()            # (6) ALL / GET / POST
    f_query = (request.GET.get("query_string") or "").strip()           # (7) URL쿼리 스트링

    # ===== apply filters =====

    # 1) URL/도메인: exact 먼저 → 없으면 contains
    # - 입력값이 URL일 수도/도메인일 수도 있으니 OR로 처리
    if f_url_or_domain:
        # exact 우선 전략을 OR에 적용하기 위해:
        # exact URL/도메인 결과가 있으면 그걸 쓰고, 없으면 contains로 fallback
        exact_qs = qs.filter(
            Q(request_url__exact=f_url_or_domain) | Q(domain__exact=f_url_or_domain)
        )
        if exact_qs.exists():
            qs = exact_qs
        else:
            qs = qs.filter(
                Q(request_url__icontains=f_url_or_domain) | Q(domain__icontains=f_url_or_domain)
            )

    # 2) 탐지 기간/시간 (create_at)
    # date input(YYYY-MM-DD)이면, create_at__date 범위로 처리
    if f_start_date:
        qs = qs.filter(create_at__date__gte=f_start_date)
    if f_end_date:
        qs = qs.filter(create_at__date__lte=f_end_date)

    # 3) 정책 이름 또는 정책 ID (JOIN)
    if f_policy_keyword:
        qs = qs.filter(
            Q(policy_id__policy_id__icontains=f_policy_keyword) |
            Q(policy_id__policy_name__icontains=f_policy_keyword)
        )

    # 4) 사용자 IP
    if f_client_ip:
        qs = qs.filter(client_ip__icontains=f_client_ip)

    # 5) 도메인/정규표현식 라디오 (policy.policy_type 기준)
    if f_policy_type in ("DOMAIN", "REGEX"):
        qs = qs.filter(policy_id__policy_type=f_policy_type)

    # 6) 메서드 라디오
    if f_method in ("GET", "POST"):
        qs = qs.filter(http_method__iexact=f_method)

    # 7) URL 쿼리 스트링
    if f_query:
        qs = qs.filter(query_string__icontains=f_query)

    # 최신순
    qs = qs.order_by("-create_at", "-id")

    paginator = Paginator(qs, 10)
    page_number = request.GET.get("page", "1")
    page_obj = paginator.get_page(page_number)

    filters = {
        "url_domain": f_url_or_domain,
        "start_date": f_start_date,
        "end_date": f_end_date,
        "policy_kw": f_policy_keyword,
        "client_ip": f_client_ip,
        "policy_type": f_policy_type,
        "method": f_method,
        "query_string": f_query,
    }

    return render(
        request,
        "integrated_detection_logs/logs_list.html",
        {
            "page_obj": page_obj,
            "filters": filters,
        },
    )