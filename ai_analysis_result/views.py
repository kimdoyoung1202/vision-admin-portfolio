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

from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import TruncHour, TruncSecond, Coalesce

from .models import AiAnalysisResult
from policy.utils_engine import send_reload_signal  # 엔진(FastAPI/Policy Engine)로 신호 보내는 유틸


# FastAPI(엔진) 상태 조회 엔드포인트
FASTAPI_STATUS_URL = "http://192.168.100.25:8000/status"


# ============================================================
# 공통: 엔진(FastAPI) CPU/MEM/RPM/P95 조회
# - Django가 FastAPI /status를 호출해서 엔진 지표를 가져온다.
# - DB에서 ai_latency_ms를 제거했으므로 "latency 시계열/값"은 엔진 응답을 우선 사용한다.
# ============================================================
def _get_engine_usage(timeout=1.5):
    """
    FastAPI /status에서 엔진 상태를 조회한다.

    return:
        (
            engine_ok,
            cpu,
            mem,
            rpm,
            lat_avg,
            lat_p95,
            series_24h,
            series_60s,
            err
        )

    engine_ok : FastAPI 응답이 정상(ok=true)인지
    cpu       : FastAPI 프로세스 CPU 사용률(%)
    mem       : FastAPI 프로세스 메모리 사용률(%)
    rpm       : 최근 1분 RPM(FastAPI 계산값)
    lat_avg   : 최근 응답속도 평균(ms)
    lat_p95   : 최근 응답속도 p95(ms)
    series_24h: (선택) 24시간 시계열
    series_60s: (선택) 60초 시계열
    err       : 실패 시 에러 문자열
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

        # KPI용 응답속도는 평균값을 우선 사용
        lat_avg = data.get("latency_ms", {}).get("avg")
        lat_p95 = data.get("latency_ms", {}).get("p95")

        # FastAPI가 시계열까지 내려주면 그대로 사용
        series_24h = data.get("series_24h")
        series_60s = data.get("series_60s")

        return True, cpu, mem, rpm, lat_avg, lat_p95, series_24h, series_60s, None

    except HTTPError as e:
        return False, None, None, None, None, None, None, None, f"HTTPError {e.code}"
    except URLError as e:
        return False, None, None, None, None, None, None, None, f"URLError {e.reason}"
    except Exception as e:
        return False, None, None, None, None, None, None, None, f"{type(e).__name__}: {e}"


# ============================================================
# AI 레코드 리스트 페이지 (필터/정렬/페이지네이션 + partial 갱신)
#
# 변경된 데이터 모델 전제:
# - 과거: request_url 중복 레코드가 여러 행으로 쌓였고, view에서 Subquery/Groupby로 대표 1개만 뽑아 느려졌다.
# - 현재: request_url은 "한 행"으로 저장되고, 중복 발생은 hit_count 증가 + last_seen 갱신으로 누적된다.
#
# 따라서:
# - "중복 제거(Subquery) 로직"은 제거한다.
# - 로그 시간 기준은 create_at이 아니라 last_seen을 사용한다.
# - 중복 건수는 dup_count가 아니라 hit_count를 사용한다.
# ============================================================
class AiRecordsView(View):
    template_name = "ai/ai_log.html"
    partial_template_name = "ai/ai_log_partial.html"  # AJAX로 리스트만 갱신할 때 사용

    def get(self, request):
        # 1) 필터 파라미터 수집
        q = (request.GET.get("q") or "").strip()
        ai_judgment = (request.GET.get("ai_judgment") or "").strip()
        is_checked = (request.GET.get("is_checked") or "").strip()
        checked_result = (request.GET.get("checked_result") or "").strip()
        policy_type = (request.GET.get("policy_type") or "").strip()
        admin = (request.GET.get("admin") or "").strip()

        # 날짜 필터는 "YYYY-MM-DD" 문자열로 들어온다는 전제
        # log_* : 탐지/발생 기준(last_seen)
        log_start = (request.GET.get("log_start") or "").strip()
        log_end = (request.GET.get("log_end") or "").strip()

        # applied_* : 정책이 실제로 적용된 시각(applied_at)
        applied_start = (request.GET.get("applied_start") or "").strip()
        applied_end = (request.GET.get("applied_end") or "").strip()

        # 정렬 옵션 (latest/confidence)
        sort = (request.GET.get("sort") or "latest").strip()

        # 페이지당 건수 제한
        per_page = request.GET.get("per_page") or "14"
        try:
            per_page = int(per_page)
        except ValueError:
            per_page = 14
        per_page = max(5, min(per_page, 100))

        # 2) 기본 QuerySet 구성
        qs = AiAnalysisResult.objects.all()

        # 정상 레코드만 기본 리스트로 보여주기
        # 오류는 confidence_score = -1로 들어오도록 설계되어 있으므로 제외한다.
        qs = qs.filter(confidence_score__gte=0)

        if checked_result == "IGNORE":
            qs = qs.filter(checked_result="IGNORE")
        elif checked_result == "ADD":
            qs = qs.filter(checked_result="ADD")
        else:
            qs = qs.exclude(checked_result="IGNORE")

        # 검색어(q): request_url 또는 domain에 포함되면 매치
        if q:
            qs = qs.filter(Q(request_url__icontains=q) | Q(domain__icontains=q))

        # ai_judgment: UI에서 Harmful/Not harm 를 confidence_score 기준으로 분류
        if ai_judgment == "Harmful":
            qs = qs.filter(confidence_score__gte=50)
        elif ai_judgment == "Not harm":
            qs = qs.filter(confidence_score__lt=50)

        # is_checked: 문자열 true/false만 허용
        if is_checked in ("true", "false"):
            qs = qs.filter(is_checked=(is_checked == "true"))

        # checked_result / policy_type / admin 필터
        # 무시는 이미 숨김 처리했으므로 ADD 위주로만 필터
        
        if policy_type:
            qs = qs.filter(policy_type=policy_type)
        if admin:
            qs = qs.filter(admin__icontains=admin)

        # 탐지 시간(last_seen) 날짜 범위
        if log_start:
            qs = qs.filter(last_seen__date__gte=log_start)
        if log_end:
            qs = qs.filter(last_seen__date__lte=log_end)

        # 정책 적용(applied_at) 날짜 범위
        if applied_start:
            qs = qs.filter(applied_at__date__gte=applied_start)
        if applied_end:
            qs = qs.filter(applied_at__date__lte=applied_end)

        # 3) 정렬
        # latest: 마지막 탐지(last_seen) 기준
        # confidence: confidence_score 우선, 그 다음 last_seen
        if sort == "confidence":
            qs = qs.order_by("-confidence_score", "-last_seen", "-id")
        else:
            qs = qs.order_by("-last_seen", "-id")

        # 4) 페이지네이션
        paginator = Paginator(qs, per_page)
        page_number = request.GET.get("page") or 1
        page_obj = paginator.get_page(page_number)

        # 5) 템플릿 컨텍스트
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

        # partial=1 + AJAX 요청이면 리스트 부분만 렌더링 (fetch 갱신용)
        if request.GET.get("partial") == "1" and request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return render(request, self.partial_template_name, context)

        return render(request, self.template_name, context)


# ============================================================
# AI 성능 페이지(HTML)
# ============================================================
class AiStatusView(View):
    def get(self, request):
        context = {
            "active_group": "ai",
            "active_menu": "ai_status",
        }
        return render(request, "ai/ai_status.html", context)


# ============================================================
# 실시간 통계 API
#
# 변경된 데이터 모델 전제:
# - create_at이 applied_at으로 이름만 바뀌었지만,
#   applied_at은 "정책 적용 시각"이므로 차트/처리량 기준 시각으로 쓰면 의미가 달라진다.
# - 탐지/발생 기준 시각은 last_seen을 사용한다.
#
# latency:
# - DB의 ai_latency_ms 필드를 제거했으므로 DB에서 Avg를 계산하지 않는다.
# - FastAPI /status에서 내려주는 p95 값을 KPI/차트에 사용한다.
#
# throughput(처리량):
# - "중복 누적 저장" 모델에서는 단순 row count는 실제 이벤트 수를 반영하지 못한다.
# - hit_count 합(Sum)을 이벤트 총량으로 사용한다.
# ============================================================
class AiStatusApiView(View):
    def get(self, request):
        """
        AI 성능 현황 화면용 JSON API

        KPI 기준
        1) latency
            - FastAPI가 내려주는 최근 응답속도 평균(latency_ms.avg)

        2) rpm
            - 실시간 RPM이 아니라 "오늘 누적 처리량"으로 사용
            - ai_analysis_result에서 정상 건(confidence_score >= 0)의 hit_count 합

        3) total_today
            - 오늘 ai_analysis_result에 들어온 전체 요청 수
            - 정상 + 오류 모두 포함
            - integrated_detection_logs는 포함하지 않음

        4) accuracy
            - 기존과 동일하게 관리자 검토 결과 기준
        """
        now_utc = timezone.now()
        now = timezone.localtime(now_utc) if getattr(settings, "USE_TZ", False) else now_utc

        # 오늘 범위
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)

        # FastAPI 엔진 상태 조회
        engine_ok, cpu_usage, memory_usage, rpm_fastapi, lat_avg_fastapi, lat_p95_fastapi, series_24h, series_60s, engine_err = _get_engine_usage()

        # ---------------------------------------------------------
        # 1) 요청수(오늘)
        # ---------------------------------------------------------
        total_today = (
            AiAnalysisResult.objects
            .filter(last_seen__gte=today_start, last_seen__lt=tomorrow_start)
            .aggregate(v=Coalesce(Sum("hit_count"), Value(0)))
        )["v"]

        # ---------------------------------------------------------
        # 2) 처리량 KPI
        # ---------------------------------------------------------
        throughput_today = (
            AiAnalysisResult.objects
            .filter(
                last_seen__gte=today_start,
                last_seen__lt=tomorrow_start,
                confidence_score__gte=0
            )
            .aggregate(v=Coalesce(Sum("hit_count"), Value(0)))
        )["v"]

        # ---------------------------------------------------------
        # 3) 정확도
        # ---------------------------------------------------------
        reviewed = AiAnalysisResult.objects.filter(is_checked=True)
        reviewed_count = reviewed.count()
        correct_count = reviewed.filter(checked_result__in=["ADD", "IGNORE"]).count()
        accuracy = round((correct_count / reviewed_count) * 100, 1) if reviewed_count else 0.0

        # ---------------------------------------------------------
        # 4) 응답속도 KPI
        # ---------------------------------------------------------
        avg_latency_ms = lat_avg_fastapi if (engine_ok and lat_avg_fastapi is not None) else 0

        tz = timezone.get_current_timezone() if getattr(settings, "USE_TZ", False) else None

        # ---------------------------------------------------------
        # 5) 차트 데이터 구성
        # ---------------------------------------------------------
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

        # 24시간 차트가 아직 필요 없더라도 프론트 호환용으로 유지
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

        # ---------------------------------------------------------
        # 6) 최근 오류
        # ---------------------------------------------------------
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
                "create_at": r["last_seen"],
                "request_url": r["request_url"],
                "confidence_score": r["confidence_score"],
            })

        # 시스템 정보
        system_info = {
            "version": "v0.1",
            "developer": "Vision",
        }

        return JsonResponse({
            "kpi": {
                # 요청수(오늘): 정상 + 오류 포함한 오늘 전체 AI 유입량
                "total_today": int(total_today or 0),

                # 처리량 KPI: 오늘 누적 처리량
                "rpm": int(throughput_today or 0),

                # 정확도
                "accuracy": accuracy,

                # 응답속도 KPI: FastAPI 평균 응답속도
                "latency": avg_latency_ms,

                # 자원 사용량
                "cpu": cpu_usage,
                "memory": memory_usage,

                # 엔진 상태
                "engine_ok": engine_ok,
                "engine_err": engine_err,
            },
            "chart": {
                # 24시간(호환용)
                "labels": labels,
                "latency_series": latency_series,
                "throughput_series": throughput_series,

                # 60초(실사용)
                "rt_labels": rt_labels,
                "rt_latency_series": rt_latency_series,
                "rt_throughput_series": rt_throughput_series,

                "cpu_spark": throughput_series,
                "mem_spark": throughput_series,
            },
            "recent_errors": recent_errors,
            "system_info": system_info,
        }, json_dumps_params={"ensure_ascii": False})


# ============================================================
# 관리자 "재검토" 버튼
# - 정책 reload가 아니라 엔진에게 "오류 재검토 작업"만 트리거
# ============================================================
@method_decorator(csrf_protect, name="dispatch")
class AiRecheckErrorsView(View):
    def post(self, request):
        try:
            send_reload_signal("recheck_errors")
            return JsonResponse({"ok": True})
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=500)


# ============================================================
# 관리자 "무시" 버튼
# - 선택한 AI 레코드를 검토 완료 + IGNORE 처리
# - 목록에서는 IGNORE 항목을 숨긴다.
# ============================================================
@method_decorator(csrf_protect, name="dispatch")
class AiIgnoreView(View):
    def post(self, request, pk):
        row = get_object_or_404(AiAnalysisResult, pk=pk)

        row.is_checked = True
        row.checked_result = "IGNORE"
        row.admin = request.user.username if request.user.is_authenticated else "system"

        # 무시는 정책 추가가 아니므로 정책 관련 값 비움
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