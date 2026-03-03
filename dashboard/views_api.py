from datetime import timedelta
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import ExtractHour, ExtractWeekDay, ExtractMonth
from django.utils import timezone

from dashboard.utils import get_prev_range  # 필요하면 유지
from integrated_detection_logs.models import IntegratedDetectionLogs
from ai_analysis_result.models import AiAnalysisResult
from policy.models import Policy


# =========================================================
# USE_TZ = False 전용 (DB도 KST, Django도 KST-naive로 사용)
# =========================================================
def _kst_now():
    # USE_TZ=False면 timezone.now()는 naive(로컬시간=KST)
    return timezone.now()


def _gran_to_kst_range(gran: str):
    """
    USE_TZ=False 기준 (naive, 로컬시간=KST)
    - day  : 오늘 00:00 ~ 지금
    - week : 이번주 월요일 00:00 ~ 지금
    - month: 이번달 1일 00:00 ~ 지금
    """
    now = _kst_now()

    if gran == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif gran == "week":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        end = now
    else:  # month
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now

    return start, end


@login_required
def kpis_api(request):
    """
    KPI도 그래프와 동일한 기간(gran) 기준으로 집계(일관성)
    - 정책은 누적(전체) 유지
    - ai/blocked는 기간 기준
    """
    gran = request.GET.get("gran", "day")
    start, end = _gran_to_kst_range(gran)

    # 정책은 누적
    policy_cnt = Policy.objects.filter(is_deleted=False).count()

    # 기간 기준
    ai_cnt = AiAnalysisResult.objects.filter(create_at__gte=start, create_at__lte=end).count()
    blocked_cnt = IntegratedDetectionLogs.objects.filter(create_at__gte=start, create_at__lte=end).count()

    # 이전 기간(네 util이 USE_TZ=False 기준으로 잘 만들어준다는 가정)
    # 만약 util이 tz-aware를 반환하면 여기서도 에러/꼬임 나니 util도 같이 수정해야 함.
    try:
        pstart, pend = get_prev_range(gran)
        ai_prev = AiAnalysisResult.objects.filter(create_at__gte=pstart, create_at__lte=pend).count()
        blocked_prev = IntegratedDetectionLogs.objects.filter(create_at__gte=pstart, create_at__lte=pend).count()
        ai_delta = ai_cnt - ai_prev
        blocked_delta = blocked_cnt - blocked_prev
    except Exception:
        # util이 아직 tz-aware면 일단 delta 0으로(그래프부터 살리기)
        ai_delta = 0
        blocked_delta = 0

    total = ai_cnt + blocked_cnt
    ratio = (blocked_cnt / total) if total else 0.0

    return JsonResponse({
        "range": gran,
        "policy_count": policy_cnt,
        "policy_delta": 0,

        "ai_count": ai_cnt,
        "ai_delta": ai_delta,

        "blocked_count": blocked_cnt,
        "blocked_delta": blocked_delta,

        "total_count": total,
        "blocked_ratio": ratio,
    })


@login_required
def timeseries_api(request):
    """
    USE_TZ=False + MySQL tz 테이블 없어도 동작하는 안전 버전
    - day  : 0~23시 (ExtractHour)
    - week : 월~일 (ExtractWeekDay)
    - month: 1~12월 (ExtractMonth)  (원하면 '일자별'로도 바꿔줄 수 있음)
    """
    gran = request.GET.get("gran", "day")
    start, end = _gran_to_kst_range(gran)

    base_qs = IntegratedDetectionLogs.objects.filter(create_at__gte=start, create_at__lte=end)
    domain_qs = base_qs.filter(policy_id__policy_type="DOMAIN")
    regex_qs = base_qs.filter(policy_id__policy_type="REGEX")

    if gran == "day":
        domain_rows = domain_qs.annotate(h=ExtractHour("create_at")).values("h").annotate(cnt=Count("id"))
        regex_rows = regex_qs.annotate(h=ExtractHour("create_at")).values("h").annotate(cnt=Count("id"))

        domain_map = {r["h"]: r["cnt"] for r in domain_rows}
        regex_map = {r["h"]: r["cnt"] for r in regex_rows}

        labels = [f"{h:02d}:00" for h in range(24)]
        domain_values = [domain_map.get(h, 0) for h in range(24)]
        regex_values = [regex_map.get(h, 0) for h in range(24)]

    elif gran == "week":
        domain_rows = domain_qs.annotate(w=ExtractWeekDay("create_at")).values("w").annotate(cnt=Count("id"))
        regex_rows = regex_qs.annotate(w=ExtractWeekDay("create_at")).values("w").annotate(cnt=Count("id"))

        domain_map = {r["w"]: r["cnt"] for r in domain_rows}
        regex_map = {r["w"]: r["cnt"] for r in regex_rows}

        order = [2, 3, 4, 5, 6, 7, 1]  # 월~일
        labels = ["월", "화", "수", "목", "금", "토", "일"]

        domain_values = [domain_map.get(k, 0) for k in order]
        regex_values = [regex_map.get(k, 0) for k in order]

    else:  # month
        # ✅ "이번 달 일자별"이 아니라 "1~12월 월별"이 싫으면 말해줘. 일자별로도 만들어줄게.
        domain_rows = domain_qs.annotate(mo=ExtractMonth("create_at")).values("mo").annotate(cnt=Count("id"))
        regex_rows = regex_qs.annotate(mo=ExtractMonth("create_at")).values("mo").annotate(cnt=Count("id"))

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
    """
    도메인 Top10 (KST 기간 기준, USE_TZ=False)
    """
    gran = request.GET.get("gran", "day")
    limit = int(request.GET.get("limit", 10))
    start, end = _gran_to_kst_range(gran)

    rows = (IntegratedDetectionLogs.objects
            .filter(create_at__gte=start, create_at__lte=end)
            .exclude(domain__isnull=True)
            .exclude(domain__exact="")
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
    정규표현식 Top10 (KST 기간 기준, USE_TZ=False)
    """
    gran = request.GET.get("gran", "day")
    limit = int(request.GET.get("limit", 10))
    start, end = _gran_to_kst_range(gran)

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
    실시간 이상 감지: 최근 window_minutes 기준 IP Top10
    (USE_TZ=False: localtime() 쓰면 안 됨)
    """
    window_minutes = int(request.GET.get("window_minutes", 10))
    limit = int(request.GET.get("limit", 10))

    now = _kst_now()
    start = now - timedelta(minutes=window_minutes)

    qs = IntegratedDetectionLogs.objects.filter(create_at__gte=start, create_at__lte=now)

    #TODO 10분동안 5회 이상 된 ip만 나오게 나중엔 수정
    rows = (qs.values("client_ip")
            .annotate(cnt=Count("id"))
            .order_by("-cnt")[:limit])

    return JsonResponse({
        "labels": [r["client_ip"] for r in rows],
        "values": [r["cnt"] for r in rows],
        "window_minutes": window_minutes,
    })