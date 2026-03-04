import json
import requests

from datetime import timedelta

from django.views import View
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.db.models.functions import TruncHour
from django.db.models import OuterRef, Subquery, Count, Q

from .models import AiAnalysisResult
from policy.utils_engine import send_reload_signal  # ✅ 너 프로젝트 구조 기준


# =========================
# 공통: 엔진(FastAPI) CPU/MEM 조회
# =========================
def _get_engine_usage():
    """
    FastAPI 엔진의 /system/usage 호출해서 CPU/MEM 가져오기
    settings.ENGINE_USAGE_URL 사용
    - 성공: (True, cpu, mem)
    - 실패: (False, 0, 0)
    """
    url = getattr(settings, "ENGINE_USAGE_URL", "http://127.0.0.1:8000/system/usage")
    timeout = getattr(settings, "ENGINE_USAGE_TIMEOUT", 1.5)
    try:
        r = requests.get(url, timeout=1.5)
        r.raise_for_status()
        data = r.json() or {}
        if data.get("ok") is True:
            cpu = float(data.get("cpu", 0) or 0)
            mem = float(data.get("memory", 0) or 0)
            return True, cpu, mem
        return False, 0.0, 0.0
    except Exception:
        return False, 0.0, 0.0


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

        # ✅ 너 기존 로직 유지: confidence_score >= 0만 기본 리스트로
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
        # ✅ 2.5) request_url 기준 대표 1개만 남기기 (MySQL 대응)
        #   - 대표 조건: confidence_score DESC -> create_at DESC -> id DESC
        #   - dup_count(동일 request_url 총 건수)도 annotate
        # ======================
        base = qs  # ✅ 필터가 모두 적용된 원본

        rep_id_subq = (
            base.filter(request_url=OuterRef("request_url"))
                .order_by("-confidence_score", "-create_at", "-id")
                .values("id")[:1]
        )

        rep_ids = (
            base.values("request_url")
                .annotate(rep_id=Subquery(rep_id_subq))
                .values("rep_id")
        )

        qs = AiAnalysisResult.objects.filter(id__in=Subquery(rep_ids))

        # ✅ dup_count: 동일 request_url의 전체 건수
        dup_count_subq = (
            base.filter(request_url=OuterRef("request_url"))
                .values("request_url")
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
            policy_type="",  # None 대신 빈값 유지
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
        # ✅ KST 기준 now를 보장 (USE_TZ=True면 timezone.now()는 UTC라 localtime 필요)
        now_utc = timezone.now()
        now = timezone.localtime(now_utc) if getattr(settings, "USE_TZ", False) else now_utc

        # ✅ '오늘' 범위(로컬 기준)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)

        # ==============================
        # 1) KPI 계산
        # ==============================
        total_today = AiAnalysisResult.objects.filter(
            create_at__gte=today_start,
            create_at__lt=tomorrow_start
        ).count()

        last_minute = now - timedelta(minutes=1)
        rpm = AiAnalysisResult.objects.filter(create_at__gte=last_minute).count()

        reviewed = AiAnalysisResult.objects.filter(is_checked=True)
        reviewed_count = reviewed.count()
        correct_count = reviewed.filter(checked_result__in=["ADD", "IGNORE"]).count()

        accuracy = 0.0
        if reviewed_count:
            accuracy = round((correct_count / reviewed_count) * 100, 1)

        # ✅ 엔진 CPU/MEM (FastAPI에서 실시간 조회)
        engine_ok, cpu_usage, memory_usage = _get_engine_usage()

        # TODO 연동 전 임시값(진짜 latency 계산 붙이면 이거 제거)
        avg_latency_ms = 128

        # ==============================
        # 2) 최근 24시간 라인차트 데이터 (✅ 1번 쿼리로 집계)
        # ==============================
        end_hour = now.replace(minute=0, second=0, microsecond=0)  # 현재 시각의 시간 시작점(로컬)
        start_hour = end_hour - timedelta(hours=23)

        chart_qs = AiAnalysisResult.objects.filter(
            create_at__gte=start_hour,
            create_at__lt=end_hour + timedelta(hours=1),
        )

        tz = timezone.get_current_timezone() if getattr(settings, "USE_TZ", False) else None

        hourly = (
            chart_qs
            .annotate(h=TruncHour("create_at", tzinfo=tz))
            .values("h")
            .annotate(cnt=Count("id"))
            .order_by("h")
        )

        hourly_map = {row["h"]: row["cnt"] for row in hourly}

        labels = []
        request_counts = []
        throughput_counts = []

        for i in range(24):
            h = start_hour + timedelta(hours=i)
            labels.append(h.strftime("%H:%M"))
            c = hourly_map.get(h, 0)
            request_counts.append(c)
            throughput_counts.append(c)

        # ==============================
        # 3) 최근 로그 테이블 (오류만)
        # ==============================
        recent_errors = list(
            AiAnalysisResult.objects
            .filter(confidence_score__lt=0)
            .order_by("-create_at")
            .values("create_at", "request_url", "confidence_score")[:10]
        )

        system_info = {
            "version": "v0.1 (TODO)",
            "developer": "Vision (TODO)",
        }

        return JsonResponse({
            "kpi": {
                "total_today": total_today,
                "rpm": rpm,
                "accuracy": accuracy,
                "latency": avg_latency_ms,
                "cpu": cpu_usage,
                "memory": memory_usage,
                "engine_ok": engine_ok,
            },
            "chart": {
                "labels": labels,
                "latency_series": request_counts,      # TODO: 진짜 latency 시계열로 교체
                "throughput_series": throughput_counts,
                "cpu_spark": request_counts,           # TODO: CPU sparkline로 교체
                "mem_spark": throughput_counts,        # TODO: MEM sparkline로 교체
            },
            "recent_errors": recent_errors,
            "system_info": system_info,
        }, json_dumps_params={"ensure_ascii": False})


@method_decorator(csrf_protect, name="dispatch")
class AiRecheckErrorsView(View):
    """
    관리자 '재검토' 버튼:
    - 엔진에게 정책 reload가 아니라 '오류(-) 재검토 작업'만 큐에 넣으라고 신호
    """
    def post(self, request):
        try:
            send_reload_signal("recheck_errors")
            return JsonResponse({"ok": True})
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=500)