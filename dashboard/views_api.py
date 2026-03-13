from datetime import timedelta

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Value
from django.db.models.functions import ExtractHour, ExtractWeekDay, ExtractMonth, Coalesce
from django.utils import timezone

from dashboard.utils import get_prev_range
from integrated_detection_logs.models import IntegratedDetectionLogs
from ai_analysis_result.models import AiAnalysisResult
from policy.models import Policy


def _kst_now():
    return timezone.now()


def _gran_to_kst_range(gran: str):
    now = _kst_now()

    if gran == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now

    elif gran == "week":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        end = now

    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now

    return start, end


@login_required
def kpis_api(request):
    gran = request.GET.get("gran", "day")
    start, end = _gran_to_kst_range(gran)

    # 현재 Policy 모델에는 is_deleted 필드가 없으므로 전체 개수 사용
    policy_cnt = Policy.objects.count()

    # AiAnalysisResult는 hit_count 누적 구조이므로 count() 대신 Sum(hit_count)
    ai_cnt = (
        AiAnalysisResult.objects
        .filter(
            last_seen__gte=start,
            last_seen__lte=end,
            confidence_score__gte=0
        )
        .aggregate(v=Coalesce(Sum("hit_count"), Value(0)))
    )["v"]

    blocked_cnt = (
        IntegratedDetectionLogs.objects
        .filter(create_at__gte=start, create_at__lte=end)
        .count()
    )

    try:
        pstart, pend = get_prev_range(gran)

        ai_prev = (
            AiAnalysisResult.objects
            .filter(
                last_seen__gte=pstart,
                last_seen__lte=pend,
                confidence_score__gte=0
            )
            .aggregate(v=Coalesce(Sum("hit_count"), Value(0)))
        )["v"]

        blocked_prev = (
            IntegratedDetectionLogs.objects
            .filter(create_at__gte=pstart, create_at__lte=pend)
            .count()
        )

        ai_delta = int((ai_cnt or 0) - (ai_prev or 0))
        blocked_delta = int((blocked_cnt or 0) - (blocked_prev or 0))

    except Exception:
        ai_delta = 0
        blocked_delta = 0

    total = int((ai_cnt or 0) + (blocked_cnt or 0))
    ratio = (blocked_cnt / total) if total else 0.0

    return JsonResponse({
        "range": gran,
        "policy_count": int(policy_cnt or 0),
        "policy_delta": 0,
        "ai_count": int(ai_cnt or 0),
        "ai_delta": int(ai_delta or 0),
        "blocked_count": int(blocked_cnt or 0),
        "blocked_delta": int(blocked_delta or 0),
        "total_count": int(total or 0),
        "blocked_ratio": ratio,
    })


@login_required
def timeseries_api(request):
    gran = request.GET.get("gran", "day")
    start, end = _gran_to_kst_range(gran)

    base_qs = IntegratedDetectionLogs.objects.filter(
        create_at__gte=start,
        create_at__lte=end
    )

    # 현재 IntegratedDetectionLogs 모델에는 policy_id FK가 없고
    # policy_type 컬럼이 직접 존재함
    domain_qs = base_qs.filter(policy_type="DOMAIN")
    regex_qs = base_qs.filter(policy_type="REGEX")

    if gran == "day":
        domain_rows = (
            domain_qs
            .annotate(h=ExtractHour("create_at"))
            .values("h")
            .annotate(cnt=Count("id"))
            .order_by("h")
        )
        regex_rows = (
            regex_qs
            .annotate(h=ExtractHour("create_at"))
            .values("h")
            .annotate(cnt=Count("id"))
            .order_by("h")
        )

        domain_map = {r["h"]: r["cnt"] for r in domain_rows}
        regex_map = {r["h"]: r["cnt"] for r in regex_rows}

        labels = [f"{h:02d}:00" for h in range(24)]
        domain_values = [domain_map.get(h, 0) for h in range(24)]
        regex_values = [regex_map.get(h, 0) for h in range(24)]

    elif gran == "week":
        domain_rows = (
            domain_qs
            .annotate(w=ExtractWeekDay("create_at"))
            .values("w")
            .annotate(cnt=Count("id"))
            .order_by("w")
        )
        regex_rows = (
            regex_qs
            .annotate(w=ExtractWeekDay("create_at"))
            .values("w")
            .annotate(cnt=Count("id"))
            .order_by("w")
        )

        domain_map = {r["w"]: r["cnt"] for r in domain_rows}
        regex_map = {r["w"]: r["cnt"] for r in regex_rows}

        # MySQL: 1=일, 2=월, ... 7=토
        order = [2, 3, 4, 5, 6, 7, 1]
        labels = ["월", "화", "수", "목", "금", "토", "일"]
        domain_values = [domain_map.get(k, 0) for k in order]
        regex_values = [regex_map.get(k, 0) for k in order]

    else:
        domain_rows = (
            domain_qs
            .annotate(mo=ExtractMonth("create_at"))
            .values("mo")
            .annotate(cnt=Count("id"))
            .order_by("mo")
        )
        regex_rows = (
            regex_qs
            .annotate(mo=ExtractMonth("create_at"))
            .values("mo")
            .annotate(cnt=Count("id"))
            .order_by("mo")
        )

        domain_map = {r["mo"]: r["cnt"] for r in domain_rows}
        regex_map = {r["mo"]: r["cnt"] for r in regex_rows}

        labels = [f"{i}월" for i in range(1, 13)]
        domain_values = [domain_map.get(i, 0) for i in range(1, 13)]
        regex_values = [regex_map.get(i, 0) for i in range(1, 13)]

    total_values = [d + r for d, r in zip(domain_values, regex_values)]

    return JsonResponse({
        "labels": labels,
        "domain": domain_values,
        "regex": regex_values,
        "total": total_values,
    })


@login_required
def top_domains_api(request):
    gran = request.GET.get("gran", "day")
    limit = int(request.GET.get("limit", 10))
    start, end = _gran_to_kst_range(gran)

    rows = (
        IntegratedDetectionLogs.objects
        .filter(create_at__gte=start, create_at__lte=end)
        .exclude(domain__isnull=True)
        .exclude(domain__exact="")
        .values("domain")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:limit]
    )

    return JsonResponse({
        "labels": [r["domain"] for r in rows],
        "values": [r["cnt"] for r in rows],
    })


@login_required
def top_regex_api(request):
    gran = request.GET.get("gran", "day")
    limit = int(request.GET.get("limit", 10))
    start, end = _gran_to_kst_range(gran)

    # 현재 IntegratedDetectionLogs 모델에는 policy_id FK가 없고
    # REGEX 여부는 policy_type, 정규식 문자열은 content 컬럼 사용
    rows = (
        IntegratedDetectionLogs.objects
        .filter(
            create_at__gte=start,
            create_at__lte=end,
            policy_type="REGEX"
        )
        .exclude(content__isnull=True)
        .exclude(content__exact="")
        .values("content")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:limit]
    )

    return JsonResponse({
        "labels": [r["content"] for r in rows],
        "values": [r["cnt"] for r in rows],
    })


@login_required
def top_ips_api(request):
    window_minutes = int(request.GET.get("window_minutes", 10))
    limit = int(request.GET.get("limit", 10))

    now = _kst_now()
    start = now - timedelta(minutes=window_minutes)

    rows = (
        IntegratedDetectionLogs.objects
        .filter(create_at__gte=start, create_at__lte=now)
        .values("client_ip")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:limit]
    )

    return JsonResponse({
        "labels": [r["client_ip"] for r in rows],
        "values": [r["cnt"] for r in rows],
        "window_minutes": window_minutes,
    })