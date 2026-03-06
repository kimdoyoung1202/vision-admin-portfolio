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


# =========================================================
# 공통 시간 함수
#
# 현재 프로젝트 전제
# - USE_TZ = False
# - DB 시간도 KST naive
# - Django timezone.now()도 KST naive처럼 사용
#
# 따라서 localtime() 같은 추가 변환 없이
# timezone.now()를 그대로 기준 시간으로 사용한다.
# =========================================================
def _kst_now():
    return timezone.now()


def _gran_to_kst_range(gran: str):
    """
    gran 값에 따라 현재 기준 조회 구간(start, end)을 만든다.

    day
        오늘 00:00:00 ~ 현재 시각

    week
        이번 주 월요일 00:00:00 ~ 현재 시각

    month
        이번 달 1일 00:00:00 ~ 현재 시각
    """
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


# =========================================================
# KPI API
#
# 프론트 대시보드의 KPI 3개와 하단 일일 패킷 현황에 사용한다.
#
# 현재 스키마 반영 사항
# - Policy는 누적 개수 유지
# - AiAnalysisResult는 create_at이 아니라 last_seen 사용
# - AiAnalysisResult는 "한 URL 1행 + hit_count 누적" 구조이므로
#   건수는 row count가 아니라 hit_count 합계를 사용하는 것이 맞다.
# - IntegratedDetectionLogs는 기존대로 create_at 기준 count 사용
#
# 반환값
# - policy_count / policy_delta
# - ai_count / ai_delta
# - blocked_count / blocked_delta
# - total_count
# - blocked_ratio
# =========================================================
@login_required
def kpis_api(request):
    gran = request.GET.get("gran", "day")
    start, end = _gran_to_kst_range(gran)

    # -----------------------------------------------------
    # 1) 정책 수
    # -----------------------------------------------------
    # 정책은 현재 활성(is_deleted=False) 기준 누적 개수를 사용한다.
    # 전일 대비는 현재 코드 구조상 별도 이전 스냅샷 개념이 없으므로 0 유지
    # (원하면 policy_history 기준으로 나중에 계산 가능)
    # -----------------------------------------------------
    policy_cnt = Policy.objects.filter(is_deleted=False).count()

    # -----------------------------------------------------
    # 2) AI 분석 수
    # -----------------------------------------------------
    # AiAnalysisResult는 중복 URL을 hit_count로 누적 저장하는 구조이므로
    # 단순 count()가 아니라 Sum("hit_count")를 사용해야
    # 실제 탐지 요청 수와 더 가깝다.
    #
    # 시간 기준은 create_at이 아니라 last_seen이다.
    # -----------------------------------------------------
    ai_cnt = (
        AiAnalysisResult.objects
        .filter(last_seen__gte=start, last_seen__lte=end, confidence_score__gte=0)
        .aggregate(v=Coalesce(Sum("hit_count"), Value(0)))
    )["v"]

    # -----------------------------------------------------
    # 3) 차단 로그 수
    # -----------------------------------------------------
    # integrated_detection_logs는 기존 로그 적재 구조 그대로이므로
    # 기간 내 row count를 그대로 사용한다.
    # -----------------------------------------------------
    blocked_cnt = IntegratedDetectionLogs.objects.filter(
        create_at__gte=start,
        create_at__lte=end
    ).count()

    # -----------------------------------------------------
    # 4) 이전 기간 대비 delta
    # -----------------------------------------------------
    # get_prev_range(gran)이 현재 프로젝트 시간 설정(USE_TZ=False)에 맞게
    # 잘 동작하면 이전 기간 집계를 계산한다.
    #
    # 만약 util이 아직 다른 시간대 전제를 가지고 있거나,
    # start/end 계산이 맞지 않아 예외가 발생하면 일단 0으로 둔다.
    # -----------------------------------------------------
    try:
        pstart, pend = get_prev_range(gran)

        ai_prev = (
            AiAnalysisResult.objects
            .filter(last_seen__gte=pstart, last_seen__lte=pend, confidence_score__gte=0)
            .aggregate(v=Coalesce(Sum("hit_count"), Value(0)))
        )["v"]

        blocked_prev = IntegratedDetectionLogs.objects.filter(
            create_at__gte=pstart,
            create_at__lte=pend
        ).count()

        ai_delta = ai_cnt - ai_prev
        blocked_delta = blocked_cnt - blocked_prev

    except Exception:
        ai_delta = 0
        blocked_delta = 0

    # -----------------------------------------------------
    # 5) 총합 및 차단 비율
    # -----------------------------------------------------
    total = ai_cnt + blocked_cnt
    ratio = (blocked_cnt / total) if total else 0.0

    return JsonResponse({
        "range": gran,

        "policy_count": policy_cnt,
        "policy_delta": 0,

        "ai_count": int(ai_cnt or 0),
        "ai_delta": int(ai_delta or 0),

        "blocked_count": int(blocked_cnt or 0),
        "blocked_delta": int(blocked_delta or 0),

        "total_count": int(total or 0),
        "blocked_ratio": ratio,
    })


# =========================================================
# 시간대별 URL 차단 로그 카운트 API
#
# 상단 시계열 차트에 사용한다.
#
# 데이터 원천
# - integrated_detection_logs
#
# 정책 타입 기준
# - DOMAIN
# - REGEX
#
# gran별 처리
# - day   : 시간대별(0~23시)
# - week  : 요일별(월~일)
# - month : 월별(1~12월)
#
# 주의
# 현재 month는 "이번 달의 일자별"이 아니라 "1월~12월 월별" 집계 형태다.
# 프론트 버튼 문구는 month지만 실제 시각화 의도는 월 단위 집계다.
# =========================================================
@login_required
def timeseries_api(request):
    gran = request.GET.get("gran", "day")
    start, end = _gran_to_kst_range(gran)

    # -----------------------------------------------------
    # 기준 로그
    # -----------------------------------------------------
    base_qs = IntegratedDetectionLogs.objects.filter(
        create_at__gte=start,
        create_at__lte=end
    )

    domain_qs = base_qs.filter(policy_id__policy_type="DOMAIN")
    regex_qs = base_qs.filter(policy_id__policy_type="REGEX")

    # -----------------------------------------------------
    # day : 0~23시
    # -----------------------------------------------------
    if gran == "day":
        domain_rows = (
            domain_qs
            .annotate(h=ExtractHour("create_at"))
            .values("h")
            .annotate(cnt=Count("id"))
        )
        regex_rows = (
            regex_qs
            .annotate(h=ExtractHour("create_at"))
            .values("h")
            .annotate(cnt=Count("id"))
        )

        domain_map = {r["h"]: r["cnt"] for r in domain_rows}
        regex_map = {r["h"]: r["cnt"] for r in regex_rows}

        labels = [f"{h:02d}:00" for h in range(24)]
        domain_values = [domain_map.get(h, 0) for h in range(24)]
        regex_values = [regex_map.get(h, 0) for h in range(24)]

    # -----------------------------------------------------
    # week : 월~일
    # MySQL ExtractWeekDay 기준은 1=일요일, 2=월요일 ... 7=토요일
    # 따라서 월~일 순서로 보이게 하려면 [2,3,4,5,6,7,1] 순으로 재배열해야 한다.
    # -----------------------------------------------------
    elif gran == "week":
        domain_rows = (
            domain_qs
            .annotate(w=ExtractWeekDay("create_at"))
            .values("w")
            .annotate(cnt=Count("id"))
        )
        regex_rows = (
            regex_qs
            .annotate(w=ExtractWeekDay("create_at"))
            .values("w")
            .annotate(cnt=Count("id"))
        )

        domain_map = {r["w"]: r["cnt"] for r in domain_rows}
        regex_map = {r["w"]: r["cnt"] for r in regex_rows}

        order = [2, 3, 4, 5, 6, 7, 1]
        labels = ["월", "화", "수", "목", "금", "토", "일"]

        domain_values = [domain_map.get(k, 0) for k in order]
        regex_values = [regex_map.get(k, 0) for k in order]

    # -----------------------------------------------------
    # month : 1월~12월
    # 현재 코드 구조상 start/end는 "이번 달 1일 ~ 지금"이지만,
    # ExtractMonth 결과를 1~12월 전체 눈금으로 그린다.
    #
    # 즉 이 코드는 엄밀히 말하면 "이번 달 기간 내에 존재한 월값"만 집계하는 셈이라
    # 구조상 gran=month 의미가 약간 애매하다.
    #
    # 그래도 기존 프론트 구조를 유지하기 위해 현재 동작 형태를 그대로 둔다.
    # 나중에 원하면 "이번 달 일자별" 또는 "최근 12개월" 방식으로 정리 가능하다.
    # -----------------------------------------------------
    else:
        domain_rows = (
            domain_qs
            .annotate(mo=ExtractMonth("create_at"))
            .values("mo")
            .annotate(cnt=Count("id"))
        )
        regex_rows = (
            regex_qs
            .annotate(mo=ExtractMonth("create_at"))
            .values("mo")
            .annotate(cnt=Count("id"))
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


# =========================================================
# 도메인 Top10 API
#
# integrated_detection_logs 기준으로
# 기간 내 가장 많이 등장한 domain 상위 N개를 반환한다.
#
# exclude(domain__isnull=True)
# exclude(domain__exact="")
# 로 빈 값/NULL 값은 제외한다.
# =========================================================
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


# =========================================================
# 정규표현식 Top10 API
#
# integrated_detection_logs 중 policy_type=REGEX 인 로그만 대상으로
# policy content(정규표현식 문자열) 기준 상위 N개를 집계한다.
# =========================================================
@login_required
def top_regex_api(request):
    gran = request.GET.get("gran", "day")
    limit = int(request.GET.get("limit", 10))
    start, end = _gran_to_kst_range(gran)

    rows = (
        IntegratedDetectionLogs.objects
        .filter(
            create_at__gte=start,
            create_at__lte=end,
            policy_id__policy_type="REGEX"
        )
        .values("policy_id__content")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:limit]
    )

    return JsonResponse({
        "labels": [r["policy_id__content"] for r in rows],
        "values": [r["cnt"] for r in rows],
    })


# =========================================================
# 실시간 이상 감지 IP Top10 API
#
# 최근 window_minutes 동안 발생한 integrated_detection_logs를 기준으로
# client_ip 상위 N개를 반환한다.
#
# 현재는 단순 count 기준 상위 정렬만 수행한다.
# 나중에 필요하면
# - 최소 발생 횟수 조건
# - 특정 정책 타입만 집계
# - 허용 IP 제외
# 같은 조건을 추가할 수 있다.
# =========================================================
@login_required
def top_ips_api(request):
    window_minutes = int(request.GET.get("window_minutes", 10))
    limit = int(request.GET.get("limit", 10))

    now = _kst_now()
    start = now - timedelta(minutes=window_minutes)

    qs = IntegratedDetectionLogs.objects.filter(
        create_at__gte=start,
        create_at__lte=now
    )

    rows = (
        qs.values("client_ip")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:limit]
    )

    return JsonResponse({
        "labels": [r["client_ip"] for r in rows],
        "values": [r["cnt"] for r in rows],
        "window_minutes": window_minutes,
    })