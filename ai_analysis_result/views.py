import json
from django.views import View
from django.shortcuts import render
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
from django.db.models import OuterRef, Subquery, Count, Q

from .models import AiAnalysisResult
from policy.utils_engine import send_reload_signal  # ✅ 너 프로젝트 구조 기준
# from .models import AiAnalysisResult  # 필요 없음(그냥 신호만 보냄)


class AiRecordsView(View):
    template_name = "ai/ai_log.html"
    partial_template_name = "ai/ai_log_partial.html"  # ✅ partial 템플릿

    def get(self, request):
        # ======================
        # 1) 필터 값 받기
        # ======================
        q = (request.GET.get("q") or "").strip()
        ai_judgment = (request.GET.get("ai_judgment") or "").strip()
        is_checked = (request.GET.get("is_checked") or "").strip()
        checked_result = (request.GET.get("checked_result") or "").strip()
        policy_type = (request.GET.get("policy_type") or "").strip()
        admin = (request.GET.get("admin") or "").strip()

        log_start = (request.GET.get("log_start") or "").strip()
        log_end = (request.GET.get("log_end") or "").strip()
        applied_start = (request.GET.get("applied_start") or "").strip()
        applied_end = (request.GET.get("applied_end") or "").strip()

        sort = (request.GET.get("sort") or "latest").strip()

        per_page = request.GET.get("per_page") or "13"
        try:
            per_page = int(per_page)
        except ValueError:
            per_page = 13
        per_page = max(5, min(per_page, 100))

        # ======================
        # 2) QS 만들기 (필터)
        # ======================
        qs = AiAnalysisResult.objects.all()
        qs = qs.filter(confidence_score__gte=0)

        if q:
            qs = qs.filter(Q(request_url__icontains=q) | Q(domain__icontains=q))

        if ai_judgment == "Harmful":
            qs = qs.filter(confidence_score__gte=50)
        elif ai_judgment == "Not harm":
            qs = qs.filter(confidence_score__lt=50)

        if is_checked in ("true", "false"):
            qs = qs.filter(is_checked=(is_checked == "true"))

        if checked_result:
            qs = qs.filter(checked_result=checked_result)

        if policy_type:
            qs = qs.filter(policy_type=policy_type)

        if admin:
            qs = qs.filter(admin__icontains=admin)

        if log_start:
            qs = qs.filter(create_at__date__gte=log_start)
        if log_end:
            qs = qs.filter(create_at__date__lte=log_end)

        if applied_start:
            qs = qs.filter(applied_at__date__gte=applied_start)
        if applied_end:
            qs = qs.filter(applied_at__date__lte=applied_end)

        # ======================
        # ✅ 2.5) Domain 기준 대표 1개만 남기기 (MySQL 대응)
        #   - 대표 조건: confidence_score DESC -> create_at DESC -> id DESC
        #   - dup_count(도메인별 총 건수)도 함께 annotate
        # ======================
        base = qs  # ✅ 필터가 모두 적용된 상태의 원본

        rep_id_subq = (
            base.filter(domain=OuterRef("domain"))
                .order_by("-confidence_score", "-create_at", "-id")
                .values("id")[:1]
        )

        rep_ids = (
            base.values("domain")
                .annotate(rep_id=Subquery(rep_id_subq))
                .values("rep_id")
        )

        qs = AiAnalysisResult.objects.filter(id__in=Subquery(rep_ids))

        dup_count_subq = (
            base.filter(domain=OuterRef("domain"))
                .values("domain")
                .annotate(c=Count("id"))
                .values("c")[:1]
        )
        qs = qs.annotate(dup_count=Subquery(dup_count_subq))

        # ======================
        # 3) 정렬 (대표 row 기준)
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

        # ✅ partial=1이면 부분만 반환 (비동기 리스트 갱신용)
        if request.GET.get("partial") == "1" and request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return render(request, self.partial_template_name, context)

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

        admin_name = _admin_name(request)

        # ✅ 같은 domain 전체에 IGNORE 적용
        updated = AiAnalysisResult.objects.filter(domain=row.domain).update(
            is_checked=True,
            checked_result="IGNORE",
            admin=admin_name,
            policy_type="",   # None 대신 빈값 유지
        )

        return JsonResponse({
            "ok": True,
            "domain": row.domain,
            "updated": updated
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
            AiAnalysisResult.objects
            .filter(confidence_score__lt=0)            # ✅ [핵심] 오류만
            .order_by("-create_at")
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
        
        
        

@method_decorator(csrf_protect, name="dispatch")
class AiRecheckErrorsView(View):
    """
    관리자 '재검토' 버튼:
    - 엔진에게 정책 reload가 아니라 '오류(-) 재검토 작업'만 큐에 넣으라고 신호
    """
    def post(self, request):
        try:
            # ✅ A-1: recheck 전용 신호
            send_reload_signal("recheck_errors")
            return JsonResponse({"ok": True})
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=500)