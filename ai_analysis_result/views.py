import json
from datetime import timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.conf import settings
from django.views import View
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator

from django.db.models import Q, Sum, Value
from django.db.models.functions import TruncHour, TruncSecond, Coalesce

from .models import AiAnalysisResult
from policy.utils_engine import send_reload_signal


# FastAPI 상태 조회 주소
FASTAPI_STATUS_URL = getattr(
    settings,
    "FASTAPI_STATUS_URL",
    "http://192.168.100.25:8000/status",
)


# FastAPI 상태 정보를 조회하는 공통 함수
# CPU, 메모리, 응답속도, 시계열 데이터를 가져온다.
def _get_engine_usage(timeout=1.5):
    """
    FastAPI /status 응답을 읽어 FastAPI 상태 정보를 반환한다.
    조회 실패 시에는 False와 에러 메시지를 반환한다.
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
            return False, None, None, None, None, None, None, None, "fastapi ok=false"

        cpu = data.get("proc", {}).get("cpu_percent")
        mem = data.get("proc", {}).get("mem_percent")
        rpm = data.get("traffic", {}).get("rpm_1m")
        lat_avg = data.get("latency_ms", {}).get("avg")
        lat_p95 = data.get("latency_ms", {}).get("p95")
        series_24h = data.get("series_24h")
        series_60s = data.get("series_60s")

        return True, cpu, mem, rpm, lat_avg, lat_p95, series_24h, series_60s, None

    except HTTPError as e:
        return False, None, None, None, None, None, None, None, f"HTTPError {e.code}"
    except URLError as e:
        return False, None, None, None, None, None, None, None, f"URLError {e.reason}"
    except Exception as e:
        return False, None, None, None, None, None, None, None, f"{type(e).__name__}: {e}"


# AI 기록 목록 페이지
# 필터, 정렬, 페이지네이션, 부분 렌더링을 처리한다.
class AiRecordsView(View):
    template_name = "ai/ai_log.html"
    partial_template_name = "ai/ai_log_partial.html"

    def get(self, request):
        # 필터 값 수집
        q = (request.GET.get("q") or "").strip()
        ai_judgment = (request.GET.get("ai_judgment") or "").strip()
        is_checked = (request.GET.get("is_checked") or "").strip()
        checked_result = (request.GET.get("checked_result") or "").strip()
        policy_type = (request.GET.get("policy_type") or "").strip()
        admin = (request.GET.get("admin") or "").strip()

        # 날짜 필터 값
        log_start = (request.GET.get("log_start") or "").strip()
        log_end = (request.GET.get("log_end") or "").strip()
        applied_start = (request.GET.get("applied_start") or "").strip()
        applied_end = (request.GET.get("applied_end") or "").strip()

        # 정렬 옵션
        sort = (request.GET.get("sort") or "latest").strip()

        # 페이지당 건수
        per_page = request.GET.get("per_page") or "12"
        try:
            per_page = int(per_page)
        except ValueError:
            per_page = 12
        per_page = max(5, min(per_page, 100))

        # 기본 목록 조회
        qs = AiAnalysisResult.objects.filter(confidence_score__gte=0)

        # 기본 목록에서는 IGNORE 항목을 숨긴다.
        if checked_result == "IGNORE":
            qs = qs.filter(checked_result="IGNORE")
        elif checked_result == "ADD":
            qs = qs.filter(checked_result="ADD")
        else:
            qs = qs.exclude(checked_result="IGNORE")

        # 검색 조건 적용
        if q:
            qs = qs.filter(Q(request_url__icontains=q) | Q(domain__icontains=q))

        if ai_judgment == "Harmful":
            qs = qs.filter(confidence_score__gte=50)
        elif ai_judgment == "Not harm":
            qs = qs.filter(confidence_score__lt=50)

        if is_checked in ("true", "false"):
            qs = qs.filter(is_checked=(is_checked == "true"))

        if policy_type:
            qs = qs.filter(policy_type=policy_type)

        if admin:
            qs = qs.filter(admin__icontains=admin)

        # 날짜 범위 필터
        if log_start:
            qs = qs.filter(last_seen__date__gte=log_start)
        if log_end:
            qs = qs.filter(last_seen__date__lte=log_end)

        if applied_start:
            qs = qs.filter(applied_at__date__gte=applied_start)
        if applied_end:
            qs = qs.filter(applied_at__date__lte=applied_end)

        # 정렬 적용
        if sort == "confidence":
            qs = qs.order_by("is_checked", "-confidence_score", "-last_seen", "-id")
        else:
            qs = qs.order_by("is_checked", "-last_seen", "-id")

        # 페이지네이션
        paginator = Paginator(qs, per_page)
        page_number = request.GET.get("page") or 1
        page_obj = paginator.get_page(page_number)

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

        # AJAX 요청이면 목록 부분만 반환
        if request.GET.get("partial") == "1" and request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return render(request, self.partial_template_name, context)

        return render(request, self.template_name, context)


# AI 성능 페이지
# 대시보드 화면을 렌더링한다.
class AiStatusView(View):
    def get(self, request):
        context = {
            "active_group": "ai",
            "active_menu": "ai_status",
        }
        return render(request, "ai/ai_status.html", context)


# AI 성능 현황 API
# KPI, 차트, 최근 오류 데이터를 JSON으로 반환한다.
class AiStatusApiView(View):
    def get(self, request):
        """
        AI 대시보드에 필요한 통계 데이터를 조회한다.
        오늘 처리량, 정확도, 응답속도, 차트 데이터, 최근 오류를 반환한다.
        """
        # 오늘 기준 시간 계산
        now_utc = timezone.now()
        now = timezone.localtime(now_utc) if getattr(settings, "USE_TZ", False) else now_utc

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)

        # 엔진 상태 조회
        engine_ok, cpu_usage, memory_usage, rpm_fastapi, lat_avg_fastapi, lat_p95_fastapi, series_24h, series_60s, engine_err = _get_engine_usage()

        # 오늘 전체 요청 수
        total_today = (
            AiAnalysisResult.objects
            .filter(last_seen__gte=today_start, last_seen__lt=tomorrow_start)
            .aggregate(v=Coalesce(Sum("hit_count"), Value(0)))
        )["v"]

        # 오늘 처리량 계산
        throughput_today = (
            AiAnalysisResult.objects
            .filter(
                last_seen__gte=today_start,
                last_seen__lt=tomorrow_start,
                confidence_score__gte=0,
            )
            .aggregate(v=Coalesce(Sum("hit_count"), Value(0)))
        )["v"]

        # 관리자 검토 기준 정확도 계산
        reviewed = AiAnalysisResult.objects.filter(is_checked=True)
        reviewed_count = reviewed.count()

        correct_count = reviewed.filter(
            (
                Q(confidence_score__gte=50) & Q(checked_result="ADD")
            ) |
            (
                Q(confidence_score__lt=50) & Q(checked_result="IGNORE")
            )
        ).count()

        accuracy = round((correct_count / reviewed_count) * 100, 1) if reviewed_count else 0.0

        # 응답속도 값 정리
        avg_latency_ms = lat_avg_fastapi if (engine_ok and lat_avg_fastapi is not None) else 0
        tz = timezone.get_current_timezone() if getattr(settings, "USE_TZ", False) else None

        # 60초 차트 데이터 구성
        if engine_ok and isinstance(series_60s, dict):
            rt_labels = series_60s.get("labels") or []
            rt_throughput_series = series_60s.get("throughput") or []
            rt_latency_series = series_60s.get("latency") or []
        else:
            sec_end = now.replace(microsecond=0)
            sec_start = sec_end - timedelta(seconds=59)

            rt_qs = AiAnalysisResult.objects.filter(
                last_seen__gte=sec_start,
                last_seen__lt=sec_end + timedelta(seconds=1),
                confidence_score__gte=0,
            )

            rt_rows = (
                rt_qs
                .annotate(s=TruncSecond("last_seen", tzinfo=tz))
                .values("s")
                .annotate(
                    throughput=Coalesce(Sum("hit_count"), Value(0)),
                )
                .order_by("s")
            )
            rt_map = {r["s"]: r for r in rt_rows}

            rt_labels, rt_throughput_series, rt_latency_series = [], [], []
            for i in range(60):
                t = sec_start + timedelta(seconds=i)
                rt_labels.append(t.strftime("%H:%M:%S"))
                row = rt_map.get(t)
                rt_throughput_series.append(int((row["throughput"] if row else 0) or 0))
                rt_latency_series.append(float(avg_latency_ms or 0))

        # 24시간 차트 데이터 구성
        if engine_ok and isinstance(series_24h, dict):
            labels = series_24h.get("labels") or []
            throughput_series = series_24h.get("throughput") or []
            latency_series = series_24h.get("latency") or []
        else:
            end_hour = now.replace(minute=0, second=0, microsecond=0)
            start_hour = end_hour - timedelta(hours=23)

            chart_qs = AiAnalysisResult.objects.filter(
                last_seen__gte=start_hour,
                last_seen__lt=end_hour + timedelta(hours=1),
                confidence_score__gte=0,
            )

            hourly = (
                chart_qs
                .annotate(h=TruncHour("last_seen", tzinfo=tz))
                .values("h")
                .annotate(
                    throughput=Coalesce(Sum("hit_count"), Value(0)),
                )
                .order_by("h")
            )
            hourly_map = {row["h"]: row for row in hourly}

            labels, throughput_series, latency_series = [], [], []
            for i in range(24):
                h = start_hour + timedelta(hours=i)
                labels.append(h.strftime("%H:%M"))
                row = hourly_map.get(h)
                throughput_series.append(int((row["throughput"] if row else 0) or 0))
                latency_series.append(float(avg_latency_ms or 0))

        # 최근 오류 목록 조회
        recent_errors_qs = (
            AiAnalysisResult.objects
            .filter(confidence_score=-1)
            .order_by("-last_seen")
            .values("last_seen", "request_url", "confidence_score")[:10]
        )

        recent_errors = []
        for r in recent_errors_qs:
            recent_errors.append({
                "last_seen": r["last_seen"],
                # 프론트 호환용 필드
                "create_at": r["last_seen"],
                "request_url": r["request_url"],
                "confidence_score": r["confidence_score"],
            })

        system_info = {
            "version": "v0.1",
            "developer": "Vision",
        }

        return JsonResponse({
            "kpi": {
                "total_today": int(total_today or 0),

                # 프론트 호환용 키 이름
                "rpm": int(throughput_today or 0),

                "accuracy": accuracy,
                "latency": avg_latency_ms,
                "cpu": cpu_usage,
                "memory": memory_usage,
                "engine_ok": engine_ok,
                "engine_err": engine_err,
            },
            "chart": {
                "labels": labels,
                "latency_series": latency_series,
                "throughput_series": throughput_series,
                "rt_labels": rt_labels,
                "rt_latency_series": rt_latency_series,
                "rt_throughput_series": rt_throughput_series,

                # 임시 호환값
                "cpu_spark": throughput_series,
                "mem_spark": throughput_series,
            },
            "recent_errors": recent_errors,
            "system_info": system_info,
        }, json_dumps_params={"ensure_ascii": False})


# 오류 재검토 요청 API
# 엔진에 재검토 작업 신호를 보낸다.
@method_decorator(csrf_protect, name="dispatch")
class AiRecheckErrorsView(View):
    def post(self, request):
        try:
            send_reload_signal("recheck_errors")
            return JsonResponse({"ok": True})
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=500)


# AI 기록 무시 처리 API
# 선택한 레코드를 검토 완료와 IGNORE 상태로 변경한다.
@method_decorator(csrf_protect, name="dispatch")
class AiIgnoreView(View):
    def post(self, request, pk):
        row = get_object_or_404(AiAnalysisResult, pk=pk)

        row.is_checked = True
        row.checked_result = "IGNORE"
        row.admin = request.user.username if request.user.is_authenticated else "system"

        # 무시 처리 시 정책 정보는 비운다.
        row.policy_type = ""
        row.applied_at = None

        row.save(update_fields=[
            "is_checked",
            "checked_result",
            "admin",
            "policy_type",
            "applied_at",
        ])

        return JsonResponse({"ok": True}, json_dumps_params={"ensure_ascii": False})