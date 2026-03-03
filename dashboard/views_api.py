from datetime import timedelta
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import TruncHour, TruncDay

from dashboard.utils import get_range, get_prev_range
from integrated_detection_logs.models import IntegratedDetectionLogs
from ai_analysis_result.models import AiAnalysisResult
from policy.models import Policy

from django.db.models.functions import ExtractHour, ExtractWeekDay, ExtractMonth
from django.utils import timezone
from datetime import timedelta




@login_required
def kpis_api(request):
    """
    (4)(5)용 핵심 KPI:
    - policy / ai / integrated 로그 수 + 전일(전주) 대비 증감
    - 차단비율: integrated / (integrated + ai)
    """
    gran = request.GET.get("gran", "day")
    start, end = get_range(gran)
    pstart, pend = get_prev_range(gran)

    policy_cnt = Policy.objects.filter(is_deleted=False).count()
    ai_cnt = AiAnalysisResult.objects.count()
    blocked_cnt = IntegratedDetectionLogs.objects.count()

    policy_prev = Policy.objects.filter(create_at__gte=pstart, create_at__lte=pend).count()
    ai_prev = AiAnalysisResult.objects.filter(create_at__gte=pstart, create_at__lte=pend).count()
    blocked_prev = IntegratedDetectionLogs.objects.filter(create_at__gte=pstart, create_at__lte=pend).count()

    total = ai_cnt + blocked_cnt
    ratio = (blocked_cnt / total) if total else 0.0  # 0~1

    return JsonResponse({
        "range": gran,

        "policy_count": policy_cnt,
        "policy_delta": policy_cnt - policy_prev,

        "ai_count": ai_cnt,
        "ai_delta": ai_cnt - ai_prev,

        "blocked_count": blocked_cnt,
        "blocked_delta": blocked_cnt - blocked_prev,

        "total_count": total,
        "blocked_ratio": ratio,
    })



@login_required
def timeseries_api(request):
    gran = request.GET.get("gran", "day")
    now = timezone.now()

    # ----------------------------
    # 기간 계산
    # ----------------------------
    if gran == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif gran == "week":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        end = now
    else:  # month
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now

    base_qs = IntegratedDetectionLogs.objects.filter(
        create_at__gte=start,
        create_at__lte=end
    )

    # DOMAIN / REGEX 분리
    domain_qs = base_qs.filter(policy_id__policy_type="DOMAIN")
    regex_qs = base_qs.filter(policy_id__policy_type="REGEX")

    # ----------------------------
    # 집계 단위별 처리
    # ----------------------------
    if gran == "day":
        # 0~23시
        domain_rows = domain_qs.annotate(h=ExtractHour("create_at")).values("h").annotate(cnt=Count("id"))
        regex_rows = regex_qs.annotate(h=ExtractHour("create_at")).values("h").annotate(cnt=Count("id"))

        domain_map = {r["h"]: r["cnt"] for r in domain_rows}
        regex_map = {r["h"]: r["cnt"] for r in regex_rows}

        labels = [f"{h:02d}:00" for h in range(24)]
        domain_values = [domain_map.get(h, 0) for h in range(24)]
        regex_values = [regex_map.get(h, 0) for h in range(24)]

    elif gran == "week":
        # 월~일
        domain_rows = domain_qs.annotate(w=ExtractWeekDay("create_at")).values("w").annotate(cnt=Count("id"))
        regex_rows = regex_qs.annotate(w=ExtractWeekDay("create_at")).values("w").annotate(cnt=Count("id"))

        domain_map = {r["w"]: r["cnt"] for r in domain_rows}
        regex_map = {r["w"]: r["cnt"] for r in regex_rows}

        order = [2, 3, 4, 5, 6, 7, 1]  # 월~일
        labels = ["월", "화", "수", "목", "금", "토", "일"]

        domain_values = [domain_map.get(k, 0) for k in order]
        regex_values = [regex_map.get(k, 0) for k in order]

    else:  # month (1~12월)
        domain_rows = domain_qs.annotate(mo=ExtractMonth("create_at")).values("mo").annotate(cnt=Count("id"))
        regex_rows = regex_qs.annotate(mo=ExtractMonth("create_at")).values("mo").annotate(cnt=Count("id"))

        domain_map = {r["mo"]: r["cnt"] for r in domain_rows}
        regex_map = {r["mo"]: r["cnt"] for r in regex_rows}

        labels = [f"{i}월" for i in range(1, 13)]
        domain_values = [domain_map.get(i, 0) for i in range(1, 13)]
        regex_values = [regex_map.get(i, 0) for i in range(1, 13)]

    # TOTAL = DOMAIN + REGEX
    total_values = [d + r for d, r in zip(domain_values, regex_values)]

    return JsonResponse({
        "labels": labels,
        "domain": domain_values,
        "regex": regex_values,
        "total": total_values,
    })


@login_required
def top_domains_api(request):
    """
    (2) 도메인 Top10 (차단 로그 기반)
    """
    gran = request.GET.get("gran", "day")
    limit = int(request.GET.get("limit", 10))
    start, end = get_range(gran)

    rows = (IntegratedDetectionLogs.objects
            .filter(create_at__gte=start, create_at__lte=end)
            .values("domain")
            .annotate(cnt=Count("id"))
            .order_by("-cnt")[:limit])

    return JsonResponse({
        "labels": [r["domain"] for r in rows],
        "values": [r["cnt"] for r in rows],
    })


@login_required
def top_regex_api(request):
    """
    (3) 정규표현식 Top10
    - policy_type='REGEX'만
    - 라벨은 policy.content(정규식 패턴)
    """
    gran = request.GET.get("gran", "day")
    limit = int(request.GET.get("limit", 10))
    start, end = get_range(gran)

    rows = (IntegratedDetectionLogs.objects
            .filter(create_at__gte=start, create_at__lte=end,
                    policy_id__policy_type="REGEX")
            .values("policy_id__content")
            .annotate(cnt=Count("id"))
            .order_by("-cnt")[:limit])

    return JsonResponse({
        "labels": [r["policy_id__content"] for r in rows],
        "values": [r["cnt"] for r in rows],
    })


@login_required
def top_ips_api(request):
    """
    (6) 실시간 이상 감지: 최근 window_minutes 기준 IP Top10
    - 5초마다 갱신
    """
    window_minutes = int(request.GET.get("window_minutes", 10))
    limit = int(request.GET.get("limit", 10))

    now = timezone.now()
    start = now - timedelta(minutes=window_minutes)
    
    qs = IntegratedDetectionLogs.objects.filter(create_at__range=(start, now))
    print("TOP_IPS window:", window_minutes, "start:", start, "now:", now, "count:", qs.count())

    #rows = (IntegratedDetectionLogs.objects
            #.filter(create_at__gte=start, create_at__lte=now)
            #.values("client_ip")
            #.annotate(cnt=Count("id"))
            #.order_by("-cnt")[:limit])
            
    rows = (qs.values("client_ip")
            .annotate(cnt=Count("id"))
            .order_by("-cnt")[:limit])

    return JsonResponse({
        "labels": [r["client_ip"] for r in rows],
        "values": [r["cnt"] for r in rows],
        "window_minutes": window_minutes,
    })