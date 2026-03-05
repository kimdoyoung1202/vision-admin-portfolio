import json
import requests

from datetime import timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.views import View
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.db.models.functions import TruncHour
from django.db.models import OuterRef, Subquery, Count, Q, Avg, FloatField
from django.db.models.functions import Coalesce
from django.db.models import Value

from .models import AiAnalysisResult
from policy.utils_engine import send_reload_signal  

FASTAPI_STATUS_URL = "http://192.168.100.25:8000/status"
# =========================
# 공통: 엔진(FastAPI) CPU/MEM 조회
# =========================
def _get_engine_usage(timeout=1.5):
    """
    return: (engine_ok, cpu, mem, rpm, p95, err)
    """
    try:
        req = Request(
            FASTAPI_STATUS_URL,
            headers={"User-Agent": "django-dashboard"},
            method="GET",
        )
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)

        if not data.get("ok"):
            return False, None, None, None, None, "fastapi ok=false"

        cpu = data.get("proc", {}).get("cpu_percent")
        mem = data.get("proc", {}).get("mem_percent")
        rpm = data.get("traffic", {}).get("rpm_1m")
        p95 = data.get("latency_ms", {}).get("p95")

        return True, cpu, mem, rpm, p95, None

    except HTTPError as e:
        return False, None, None, None, None, f"HTTPError {e.code}"
    except URLError as e:
        return False, None, None, None, None, f"URLError {e.reason}"
    except Exception as e:
        return False, None, None, None, None, f"{type(e).__name__}: {e}"

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
    실시간 통계 API
    - KPI: FastAPI /status 우선
    - 차트: (1) 최근 60초 실시간용(초당) + (2) 최근 24시간(시간당)
    """

    def get(self, request):
        # ✅ KST 기준 now
        now_utc = timezone.now()
        now = timezone.localtime(now_utc) if getattr(settings, "USE_TZ", False) else now_utc

        # ✅ 오늘 범위
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)

        # ==============================
        # 0) FastAPI 실시간 지표
        # ==============================
        engine_ok, cpu_usage, memory_usage, rpm_fastapi, p95_fastapi, engine_err = _get_engine_usage()

        # ==============================
        # 1) KPI
        # ==============================
        total_today = AiAnalysisResult.objects.filter(
            create_at__gte=today_start,
            create_at__lt=tomorrow_start
        ).count()

        # RPM: FastAPI 우선, 실패 시 DB 1분 count
        last_minute = now - timedelta(minutes=1)
        rpm = rpm_fastapi if rpm_fastapi is not None else AiAnalysisResult.objects.filter(create_at__gte=last_minute).count()

        reviewed = AiAnalysisResult.objects.filter(is_checked=True)
        reviewed_count = reviewed.count()
        correct_count = reviewed.filter(checked_result__in=["ADD", "IGNORE"]).count()
        accuracy = round((correct_count / reviewed_count) * 100, 1) if reviewed_count else 0.0

        # Latency(KPI): FastAPI p95 우선(없으면 0)
        avg_latency_ms = p95_fastapi if (engine_ok and p95_fastapi is not None) else 0

        # ==============================
        # 2-A) ✅ 실시간 차트(최근 60초)
        #   - 처리량: 초당 count
        #   - 응답속도: 초당 avg(ai_latency_ms) (0/NULL/음수 제외)
        # ==============================
        sec_end = now.replace(microsecond=0)
        sec_start = sec_end - timedelta(seconds=59)

        rt_qs = AiAnalysisResult.objects.filter(
            create_at__gte=sec_start,
            create_at__lt=sec_end + timedelta(seconds=1),
        )

        # MySQL에서도 안전하게 "초" 단위 그룹핑: TruncSecond 사용
        from django.db.models.functions import TruncSecond  # 여기서 import해도 됨

        rt_rows = (
            rt_qs
            .annotate(s=TruncSecond("create_at", tzinfo=timezone.get_current_timezone() if getattr(settings, "USE_TZ", False) else None))
            .values("s")
            .annotate(
                cnt=Count("id"),
                avg_latency=Coalesce(
                    Avg("ai_latency_ms", filter=Q(ai_latency_ms__gt=0), output_field=FloatField()),
                    Value(0.0)
                )
            )
            .order_by("s")
        )

        rt_map = {r["s"]: r for r in rt_rows}

        rt_labels = []
        rt_throughput = []
        rt_latency = []

        for i in range(60):
            t = sec_start + timedelta(seconds=i)
            rt_labels.append(t.strftime("%H:%M:%S"))

            row = rt_map.get(t)
            if row:
                rt_throughput.append(int(row["cnt"] or 0))
                rt_latency.append(float(row["avg_latency"] or 0.0))
            else:
                rt_throughput.append(0)
                rt_latency.append(0.0)  # ✅ None 금지(차트 끊김 방지)

        # ==============================
        # 2-B) ✅ 24시간(시간단위) 차트 (원하면 유지)
        # ==============================
        end_hour = now.replace(minute=0, second=0, microsecond=0)
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
            .annotate(
                cnt=Count("id"),
                avg_latency=Coalesce(
                    Avg("ai_latency_ms", filter=Q(ai_latency_ms__gt=0), output_field=FloatField()),
                    Value(0.0)
                ),
            )
            .order_by("h")
        )

        hourly_map = {row["h"]: row for row in hourly}

        labels = []
        throughput_series = []
        latency_series = []

        for i in range(24):
            h = start_hour + timedelta(hours=i)
            labels.append(h.strftime("%H:%M"))

            row = hourly_map.get(h)
            if row:
                throughput_series.append(int(row["cnt"] or 0))
                latency_series.append(float(row["avg_latency"] or 0.0))
            else:
                throughput_series.append(0)
                latency_series.append(0.0)  # ✅ None 금지

        # ==============================
        # 3) 최근 오류
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
                "engine_err": engine_err,
            },
            "chart": {
                # ✅ 기존 24시간 차트(유지)
                "labels": labels,
                "latency_series": latency_series,
                "throughput_series": throughput_series,

                # ✅ 새로 추가: 실시간 60초 차트
                "rt_labels": rt_labels,
                "rt_latency_series": rt_latency,
                "rt_throughput_series": rt_throughput,

                "cpu_spark": throughput_series,  # TODO
                "mem_spark": throughput_series,  # TODO
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