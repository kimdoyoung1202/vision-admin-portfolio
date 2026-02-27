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
@login_required
def timeseries_api(request):
    """
    gran:
        - day   : 오늘(0~23시)
        - week  : 이번주(월~일) 요일별
        - month : 올해(1~12월) 월별

    ptype:
        - all | DOMAIN | REGEX
    """
    gran = request.GET.get("gran", "day")     # day|week|month
    ptype = request.GET.get("ptype", "all")  # all|DOMAIN|REGEX

    now = timezone.localtime()

    # ---- 기준 기간 계산 ----
    if gran == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif gran == "week":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        end = now
    else:  # month
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now

    qs = IntegratedDetectionLogs.objects.filter(create_at__gte=start, create_at__lte=end)

    if ptype != "all":
        qs = qs.filter(policy_id__policy_type=ptype)

    # ---- 집계 단위별 labels/values ----
    if gran == "day":
        rows = (qs.annotate(h=ExtractHour("create_at"))
                .values("h")
                .annotate(cnt=Count("id"))
                .order_by("h"))
        m = {r["h"]: r["cnt"] for r in rows}
        labels = [f"{h:02d}:00" for h in range(24)]
        values = [m.get(h, 0) for h in range(24)]

    elif gran == "week":
        # ExtractWeekDay: 일=1, 월=2 ... 토=7 (Django/DB에 따라 동일)
        rows = (qs.annotate(w=ExtractWeekDay("create_at"))
                .values("w")
                .annotate(cnt=Count("id"))
                .order_by("w"))
        m = {r["w"]: r["cnt"] for r in rows}

        # 월~일 순서로 보여주고 싶으니까 매핑
        # ExtractWeekDay 기준: 월=2, 화=3, 수=4, 목=5, 금=6, 토=7, 일=1
        order = [2, 3, 4, 5, 6, 7, 1]  # 월~일
        labels = ["월", "화", "수", "목", "금", "토", "일"]
        values = [m.get(k, 0) for k in order]

        # ⚠️ 월~금만 원하면 아래로 바꾸면 됨:
        # order = [2,3,4,5,6]
        # labels = ["월","화","수","목","금"]
        # values = [m.get(k,0) for k in order]

    else:  # month: 1~12
        rows = (qs.annotate(mo=ExtractMonth("create_at"))
                .values("mo")
                .annotate(cnt=Count("id"))
                .order_by("mo"))
        m = {r["mo"]: r["cnt"] for r in rows}
        labels = [f"{i}월" for i in range(1, 13)]
        values = [m.get(i, 0) for i in range(1, 13)]

    return JsonResponse({
        "gran": gran,
        "ptype": ptype,
        "labels": labels,
        "values": values,
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

    # "최근 N분"
    from django.utils import timezone
    now = timezone.localtime()
    start = now - timedelta(minutes=window_minutes)

    rows = (IntegratedDetectionLogs.objects
            .filter(create_at__gte=start, create_at__lte=now)
            .values("client_ip")
            .annotate(cnt=Count("id"))
            .order_by("-cnt")[:limit])

    return JsonResponse({
        "labels": [r["client_ip"] for r in rows],
        "values": [r["cnt"] for r in rows],
        "window_minutes": window_minutes,
    })