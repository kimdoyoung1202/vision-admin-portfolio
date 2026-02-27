from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from datetime import timedelta
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.core.cache import cache

from policy.models import Policy
from ai_analysis_result.models import AiAnalysisResult
from integrated_detection_logs.models import IntegratedDetectionLogs  # 너 실제 모델명으로 교체

@login_required
def kpis_api(request):
    now = timezone.localtime(timezone.now())
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yday_start = today_start - timedelta(days=1)

    # ✅ 누적 전체 (휴지통 제외)
    policy_total = Policy.objects.filter(is_deleted=False).count()
    ai_total = AiAnalysisResult.objects.count()
    blocked_total = IntegratedDetectionLogs.objects.count()

    # ✅ 전일 대비 = (오늘 생성 - 어제 생성)
    policy_today = Policy.objects.filter(is_deleted=False, create_at__gte=today_start).count()
    policy_yday = Policy.objects.filter(is_deleted=False, create_at__gte=yday_start, create_at__lt=today_start).count()
    policy_delta = policy_today - policy_yday

    ai_today = AiAnalysisResult.objects.filter(create_at__gte=today_start).count()
    ai_yday = AiAnalysisResult.objects.filter(create_at__gte=yday_start, create_at__lt=today_start).count()
    ai_delta = ai_today - ai_yday

    blocked_today = IntegratedDetectionLogs.objects.filter(create_at__gte=today_start).count()
    blocked_yday = IntegratedDetectionLogs.objects.filter(create_at__gte=yday_start, create_at__lt=today_start).count()
    blocked_delta = blocked_today - blocked_yday

    total = ai_total + blocked_total
    ratio = (blocked_total / total) if total else 0.0

    return JsonResponse({
        "range": "total",
        "policy_count": policy_total,
        "policy_delta": policy_delta,
        "ai_count": ai_total,
        "ai_delta": ai_delta,
        "blocked_count": blocked_total,
        "blocked_delta": blocked_delta,
        "total_count": total,
        "blocked_ratio": ratio,
    })

@login_required
def dashboard_view(request):
    return render(request, "dashboard/dashboard.html", {
        "active_menu": "dashboard",
        "active_group": "dashboard",
    })
