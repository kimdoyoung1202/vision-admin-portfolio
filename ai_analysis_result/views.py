import json
from django.views import View
from django.shortcuts import render
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count

from .models import AiAnalysisResult


class AiRecordsView(View):
    template_name = "ai/ai_log.html"

    def get(self, request):
        # ======================
        # 1) 필터 값 받기
        # ======================
        q = (request.GET.get("q") or "").strip()  # URL/도메인
        ai_judgment = (request.GET.get("ai_judgment") or "").strip()  # Harmful/Not harm 등(판단결과)
        is_checked = (request.GET.get("is_checked") or "").strip()  # true/false
        checked_result = (request.GET.get("checked_result") or "").strip()  # 추가/무시 (관리자 검토 결과)
        policy_type = (request.GET.get("policy_type") or "").strip()  # Domain/Regex
        admin = (request.GET.get("admin") or "").strip()  # 작성자

        # 로그 시간(create_at) 범위
        log_start = (request.GET.get("log_start") or "").strip()
        log_end = (request.GET.get("log_end") or "").strip()

        # 정책 추가 시간(applied_at) 범위
        applied_start = (request.GET.get("applied_start") or "").strip()
        applied_end = (request.GET.get("applied_end") or "").strip()

        # 정렬
        sort = (request.GET.get("sort") or "latest").strip()  # latest / confidence

        # 페이지네이션
        per_page = request.GET.get("per_page") or "15"
        try:
            per_page = int(per_page)
        except ValueError:
            per_page = 15
        per_page = max(5, min(per_page, 100))  # 5~100 안전장치

        # ======================
        # 2) QS 만들기
        # ======================
        qs = AiAnalysisResult.objects.all()

        # URL/도메인 검색
        if q:
            qs = qs.filter(Q(request_url__icontains=q) | Q(domain__icontains=q))

        # 판단 결과(checked_result 컬럼을 "AI판단 결과"로 사용)
        if ai_judgment == "Harmful":
            qs = qs.filter(confidence_score__gte=50)
        elif ai_judgment == "Not harm":
            qs = qs.filter(confidence_score__lt=50)

        # 관리자 검토 여부
        if is_checked in ("true", "false"):
            qs = qs.filter(is_checked=(is_checked == "true"))

        # 관리자 검토 결과 (추가/무시)
        # 설계도에서는 "검토 여부가 선택되면 활성화"지만, 서버 필터는 값 있으면 적용
        if checked_result:
            qs = qs.filter(checked_result=checked_result)  # ✅ 여기 주의!
            # 만약 DB에서 "관리자 검토 결과"가 checked_result가 아니라면
            # 컬럼명을 admin_checked_result 같은 걸로 바꿔서 여기를 수정해야 함.

        # 정책 타입
        if policy_type:
            qs = qs.filter(policy_type=policy_type)

        # 작성자(검토자)
        if admin:
            qs = qs.filter(admin__icontains=admin)

        # 로그시간 범위(create_at)
        if log_start:
            qs = qs.filter(create_at__date__gte=log_start)
        if log_end:
            qs = qs.filter(create_at__date__lte=log_end)

        # 정책추가시간 범위(applied_at)
        if applied_start:
            qs = qs.filter(applied_at__date__gte=applied_start)
        if applied_end:
            qs = qs.filter(applied_at__date__lte=applied_end)

        # ======================
        # 3) 정렬
        # ======================
        if sort == "confidence":
            qs = qs.order_by("-confidence_score", "-create_at")
        else:
            qs = qs.order_by("-create_at")

        # ======================
        # 4) 페이지네이션
        # ======================
        paginator = Paginator(qs, per_page)
        page_number = request.GET.get("page") or 1
        page_obj = paginator.get_page(page_number)

        # ======================
        # 5) 컨텍스트
        # ======================
        filters = {
            "q": q,
            "ai_judgment": ai_judgment,
            "is_checked": is_checked,
            "checked_result": checked_result,
            "policy_type": policy_type,
            "admin": admin,
            "log_start": log_start,
            "log_end": log_end,
            "applied_start": applied_start,
            "applied_end": applied_end,
            "sort": sort,
            "per_page": str(per_page),
        }

        context = {
            "active_group": "ai",
            "active_menu": "ai_records",
            "filters": filters,
            "page_obj": page_obj,
        }
        return render(request, self.template_name, context)
    
class AiStatusView(View):
    def get(self, request):
        context = {
            "active_group": "ai",
            "active_menu": "ai_status",
        }
        return render(request, "ai/ai_status.html", context)
    
    
def _admin_name(request) -> str:
    u = getattr(request, "user", None)
    if u and getattr(u, "is_authenticated", False):
        return getattr(u, "username", None) or "ADMIN"
    return "ADMIN"

@method_decorator(csrf_protect, name="dispatch")
class AiIgnoreView(View):

    def post(self, request, pk):
        print("IGNORE POST HIT:", pk)

        row = get_object_or_404(AiAnalysisResult, pk=pk)

        row.is_checked = True
        row.checked_result = "IGNORE"
        row.admin = _admin_name(request)

        # ❗ None 넣지 말고 빈값으로 처리 (운영DB 안정)
        row.policy_type = ""
        # applied_at 은 건드리지 않는다 (timestamp 오류 방지)

        row.save()

        return JsonResponse({"ok": True})
    
    
    class AiStatusApiView(View):
        """
        5초마다 호출되는 실시간 통계 API
        """

        def get(self, request):
            now = timezone.now()
            today = now.date()
            last_24h = now - timedelta(hours=24)

            # ==============================
            # 1) KPI 계산
            # ==============================

            today_qs = AiAnalysisResult.objects.filter(create_at__date=today)
            total_today = today_qs.count()

            # 분당 처리량 (RPM)
            last_minute = now - timedelta(minutes=1)
            rpm = AiAnalysisResult.objects.filter(create_at__gte=last_minute).count()

            # 정확도 계산 (관리자 검토 기준)
            reviewed = AiAnalysisResult.objects.filter(is_checked=True)
            reviewed_count = reviewed.count()
            correct_count = reviewed.filter(
                checked_result__in=["ADD", "IGNORE"]
            ).count()

            accuracy = 0
            if reviewed_count > 0:
                accuracy = round((correct_count / reviewed_count) * 100, 1)

            # TODO: FastAPI 엔진 latency 연동 위치
            avg_latency_ms = 128  # 임시값

            # TODO: FastAPI 시스템 모니터링 연동 위치
            cpu_usage = 65
            memory_usage = 54

            # ==============================
            # 2) 최근 24시간 라인차트 데이터
            # ==============================
            labels = []
            request_counts = []
            throughput_counts = []

            for i in range(24):
                hour_start = now - timedelta(hours=23 - i)
                hour_end = hour_start + timedelta(hours=1)

                count = AiAnalysisResult.objects.filter(
                    create_at__gte=hour_start,
                    create_at__lt=hour_end
                ).count()

                labels.append(hour_start.strftime("%H:%M"))
                request_counts.append(count)
                throughput_counts.append(count)  # 동일 데이터 재사용

            # ==============================
            # 3) 최근 로그 테이블
            # ==============================
            recent_logs = list(
                AiAnalysisResult.objects.order_by("-create_at")
                .values("create_at", "request_url", "confidence_score")[:10]
            )

            return JsonResponse({
                "kpi": {
                    "total_today": total_today,
                    "rpm": rpm,
                    "accuracy": accuracy,
                    "latency": avg_latency_ms,
                    "cpu": cpu_usage,
                    "memory": memory_usage,
                },
                "chart": {
                    "labels": labels,
                    "requests": request_counts,
                    "throughput": throughput_counts,
                },
                "recent_logs": recent_logs,
            })
            
            
class AiStatusApiView(View):
    """
    5초마다 호출되는 실시간 통계 API
    """

    def get(self, request):
        now = timezone.now()
        today = now.date()
        last_24h = now - timedelta(hours=24)

        # ==============================
        # 1) KPI 계산
        # ==============================

        today_qs = AiAnalysisResult.objects.filter(create_at__date=today)
        total_today = today_qs.count()

        # 분당 처리량 (RPM)
        last_minute = now - timedelta(minutes=1)
        rpm = AiAnalysisResult.objects.filter(create_at__gte=last_minute).count()

        # 정확도 계산 (관리자 검토 기준)
        reviewed = AiAnalysisResult.objects.filter(is_checked=True)
        reviewed_count = reviewed.count()
        correct_count = reviewed.filter(
            checked_result__in=["ADD", "IGNORE"]
        ).count()

        accuracy = 0
        if reviewed_count > 0:
            accuracy = round((correct_count / reviewed_count) * 100, 1)

        # TODO: FastAPI 엔진 latency 연동 위치
        avg_latency_ms = 128  # 임시값

        # TODO: FastAPI 시스템 모니터링 연동 위치
        cpu_usage = 65
        memory_usage = 54

        # ==============================
        # 2) 최근 24시간 라인차트 데이터
        # ==============================
        labels = []
        request_counts = []
        throughput_counts = []

        for i in range(24):
            hour_start = now - timedelta(hours=23 - i)
            hour_end = hour_start + timedelta(hours=1)

            count = AiAnalysisResult.objects.filter(
                create_at__gte=hour_start,
                create_at__lt=hour_end
            ).count()

            labels.append(hour_start.strftime("%H:%M"))
            request_counts.append(count)
            throughput_counts.append(count)  # 동일 데이터 재사용

        # ==============================
        # 3) 최근 로그 테이블
        # ==============================
        recent_errors = list(
            AiAnalysisResult.objects.order_by("-create_at")
            .values("create_at", "request_url", "confidence_score")[:10]
        )

        # 시스템 정보(임시)
        system_info = {
            "version": "v0.1 (TODO)",
            "developer": "Vision (TODO)",
        }

        return JsonResponse({
            "kpi": {
                "total_today": total_today,
                "rpm": rpm,
                "accuracy": accuracy,
                "latency": avg_latency_ms,  # TODO: FastAPI latency 연동
                "cpu": cpu_usage,           # TODO: 시스템 모니터링 연동
                "memory": memory_usage,     # TODO: 시스템 모니터링 연동
                "engine_ok": True,          # TODO: FastAPI healthcheck 연동
            },
            "chart": {
                "labels": labels,
                "latency_series": request_counts,     # TODO: 나중에 진짜 latency 시계열로 교체
                "throughput_series": throughput_counts,
                "cpu_spark": request_counts,          # TODO: CPU sparkline으로 교체
                "mem_spark": throughput_counts,       # TODO: MEM sparkline으로 교체
            },
            "recent_errors": recent_errors,
            "system_info": system_info,
        })