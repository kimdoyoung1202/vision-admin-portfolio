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

    # =========================
    # filters from GET
    # =========================
    f_url_or_domain = (request.GET.get("url_domain") or "").strip()
    f_start_dt = (request.GET.get("start_dt") or "").strip()       # datetime-local
    f_end_dt = (request.GET.get("end_dt") or "").strip()           # datetime-local
    f_policy_keyword = (request.GET.get("policy_kw") or "").strip()
    f_client_ip = (request.GET.get("client_ip") or "").strip()
    f_policy_type = (request.GET.get("policy_type") or "").strip().upper()
    f_method = (request.GET.get("method") or "").strip().upper()
    f_query = (request.GET.get("query_string") or "").strip()

    # =========================
    # 1) URL/도메인
    # exact 먼저 -> 없으면 contains
    # request_url OR domain
    # =========================
    if f_url_or_domain:
        exact_qs = qs.filter(
            Q(request_url__exact=f_url_or_domain) |
            Q(domain__exact=f_url_or_domain)
        )
        if exact_qs.exists():
            qs = exact_qs
        else:
            qs = qs.filter(
                Q(request_url__icontains=f_url_or_domain) |
                Q(domain__icontains=f_url_or_domain)
            )

    # =========================
    # 2) 탐지 기간/시간(create_at)
    # =========================
    if f_start_dt:
        qs = qs.filter(create_at__gte=f_start_dt)

    if f_end_dt:
        qs = qs.filter(create_at__lte=f_end_dt)

    # =========================
    # 3) 정책 이름 / 정책 ID / 정책 content
    # dashboard에서 정규표현식 키워드 넘길 수도 있으니
    # content 검색도 같이 포함
    # =========================
    if f_policy_keyword:
        qs = qs.filter(
            Q(policy_id__policy_id__icontains=f_policy_keyword) |
            Q(policy_id__policy_name__icontains=f_policy_keyword) |
            Q(policy_id__content__icontains=f_policy_keyword)
        )

    # =========================
    # 4) 사용자 IP
    # =========================
    if f_client_ip:
        qs = qs.filter(client_ip__icontains=f_client_ip)

    # =========================
    # 5) 정책 타입
    # =========================
    if f_policy_type in ("DOMAIN", "REGEX"):
        qs = qs.filter(policy_id__policy_type=f_policy_type)

    # =========================
    # 6) 메서드
    # =========================
    if f_method in ("GET", "POST"):
        qs = qs.filter(http_method__iexact=f_method)

    # =========================
    # 7) URL query string
    # =========================
    if f_query:
        qs = qs.filter(query_string__icontains=f_query)

    # 최신순
    qs = qs.order_by("-create_at", "-id")

    paginator = Paginator(qs, 10)
    page_number = request.GET.get("page", "1")
    page_obj = paginator.get_page(page_number)

    filters = {
        "url_domain": f_url_or_domain,
        "start_dt": f_start_dt,
        "end_dt": f_end_dt,
        "policy_kw": f_policy_keyword,
        "client_ip": f_client_ip,
        "policy_type": f_policy_type,
        "method": f_method,
        "query_string": f_query,
    }

    # Ajax 요청이면 partial만 반환
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    template = (
        "integrated_detection_logs/log_partial.html"
        if is_ajax
        else "integrated_detection_logs/logs_list.html"
    )

    return render(request, template, {
        "page_obj": page_obj,
        "filters": filters,
    })