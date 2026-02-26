from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from datetime import timedelta
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.core.cache import cache

from policy.models import Policy
from ai_analysis_result.models import AiAnalysisResult
from intergrated_detection_logs.models import IntegratedDetectionLogs  # 너 실제 모델명으로 교체

@require_GET
def kpis_api(request):
    """
    누적 count + 전일 대비(오늘 생성 - 어제 생성)
    반환 키는 프론트에서 이미 쓰는 키와 동일하게 유지:
    policy_count, policy_delta, ai_count, ai_delta, blocked_count, blocked_delta, total_count
    """
    # 5초 캐시 (대시보드 5초 갱신이랑 동일)
    cache_key = "dash:kpis:v1"
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached)

    # ✅ KST 기준 날짜 경계
    now = timezone.localtime()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yday_start = today_start - timedelta(days=1)

    # ---- Policy (휴지통 제외)
    policy_total = Policy.objects.filter(is_deleted=False).count()

    # "오늘 생성된 정책 수" / "어제 생성된 정책 수"
    # ※ create_at 필드명이 다르면 바꿔줘 (created_at / created_at 등)
    policy_today = Policy.objects.filter(
        is_deleted=False,
        create_at__gte=today_start
    ).count()
    policy_yday = Policy.objects.filter(
        is_deleted=False,
        create_at__gte=yday_start,
        create_at__lt=today_start
    ).count()
    policy_delta = policy_today - policy_yday

    # ---- AI 분석 결과
    ai_total = AiAnalysisResult.objects.count()
    # create_at 필드명 확인 필요(너 요약에서 create_at 있다고 했음)
    ai_today = AiAnalysisResult.objects.filter(create_at__gte=today_start).count()
    ai_yday = AiAnalysisResult.objects.filter(create_at__gte=yday_start, create_at__lt=today_start).count()
    ai_delta = ai_today - ai_yday

    # ---- 탐지 로그 (전체 누적)
    blocked_total = IntegratedDetectionLogs.objects.count()
    # create_at 필드명 확인 필요
    blocked_today = IntegratedDetectionLogs.objects.filter(create_at__gte=today_start).count()
    blocked_yday = IntegratedDetectionLogs.objects.filter(create_at__gte=yday_start, create_at__lt=today_start).count()
    blocked_delta = blocked_today - blocked_yday

    # total_count는 “오늘 수집량”으로 쓰고 싶으면 (오늘 AI + 오늘 로그)
    # 아니면 "누적 총합"으로 쓰고 싶으면 total_total로 바꾸면 됨
    total_count = ai_today + blocked_today  # ✅ 오늘 수집한 패킷/레코드 총합 컨셉이면 이게 맞음

    data = {
        "range": "total",  # 이제 day 집계가 아니라 "total KPI"라는 의미
        "policy_count": policy_total,
        "policy_delta": policy_delta,

        "ai_count": ai_total,
        "ai_delta": ai_delta,

        "blocked_count": blocked_total,
        "blocked_delta": blocked_delta,

        "total_count": total_count,
    }

    cache.set(cache_key, data, 5)
    return JsonResponse(data)

@login_required
def dashboard_view(request):
    return render(request, "dashboard/dashboard.html", {
        "active_menu": "dashboard",
        "active_group": "dashboard",
    })
