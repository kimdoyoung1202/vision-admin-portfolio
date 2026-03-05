import json
from datetime import timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.conf import settings
from django.views import View
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator
from django.utils import timezone

from django.db.models import OuterRef, Subquery, Count, Q, Avg, FloatField, Value
from django.db.models.functions import TruncHour, Coalesce

from .models import AiAnalysisResult
from policy.utils_engine import send_reload_signal  # 엔진(FastAPI/Policy Engine)로 신호 보내는 유틸


# FastAPI(엔진) 상태 조회 엔드포인트
FASTAPI_STATUS_URL = "http://192.168.100.25:8000/status"


# ============================================================
# 공통: 엔진(FastAPI) CPU/MEM/RPM/P95 조회
# - Django가 직접 FastAPI /status를 호출해서
#   "엔진 지표"를 우선적으로 KPI에 반영하기 위한 함수
# ============================================================
def _get_engine_usage(timeout=1.5):
    """
    return: (engine_ok, cpu, mem, rpm, p95, err)

    engine_ok: FastAPI 응답이 정상(ok=true)인지
    cpu       : 프로세스 CPU 사용률 (%)
    mem       : 프로세스 메모리 사용률 (%)
    rpm       : 최근 1분 RPM (FastAPI가 계산해준 값)
    p95       : 지연시간 p95(ms) (FastAPI가 계산해준 값)
    err       : 실패 시 에러 메시지 문자열
    """
    try:
        # urllib 사용: requests 없이도 가능(프로젝트 의존성 줄이기 좋음)
        req = Request(
            FASTAPI_STATUS_URL,
            headers={"User-Agent": "django-dashboard"},
            method="GET",
        )

        # timeout: FastAPI 죽었을 때 Django가 오래 멈추는 걸 방지
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)

        # FastAPI가 {"ok": true/false} 형태로 내려준다는 가정
        if not data.get("ok"):
            return False, None, None, None, None, "fastapi ok=false"

        # 방어적으로 get 체이닝 (키가 없으면 None)
        cpu = data.get("proc", {}).get("cpu_percent")
        mem = data.get("proc", {}).get("mem_percent")
        rpm = data.get("traffic", {}).get("rpm_1m")
        p95 = data.get("latency_ms", {}).get("p95")

        return True, cpu, mem, rpm, p95, None

    except HTTPError as e:
        # FastAPI가 살아있지만 4xx/5xx로 응답한 케이스
        return False, None, None, None, None, f"HTTPError {e.code}"
    except URLError as e:
        # 연결 불가(DNS/라우팅/거절 등)
        return False, None, None, None, None, f"URLError {e.reason}"
    except Exception as e:
        # 나머지 예외 (json 파싱 실패 등 포함)
        return False, None, None, None, None, f"{type(e).__name__}: {e}"


# ============================================================
# AI 레코드 리스트 페이지 (필터/정렬/페이지네이션 + partial 갱신)
# ============================================================
class AiRecordsView(View):
    template_name = "ai/ai_log.html"
    partial_template_name = "ai/ai_log_partial.html"  # AJAX로 리스트만 갱신할 때 사용

    def get(self, request):
        # ----------------------
        # 1) 필터 파라미터 수집
        # ----------------------
        q = (request.GET.get("q") or "").strip()
        ai_judgment = (request.GET.get("ai_judgment") or "").strip()
        is_checked = (request.GET.get("is_checked") or "").strip()
        checked_result = (request.GET.get("checked_result") or "").strip()
        policy_type = (request.GET.get("policy_type") or "").strip()
        admin = (request.GET.get("admin") or "").strip()

        # 날짜 필터는 "YYYY-MM-DD" 문자열로 들어온다는 전제
        log_start = (request.GET.get("log_start") or "").strip()
        log_end = (request.GET.get("log_end") or "").strip()
        applied_start = (request.GET.get("applied_start") or "").strip()
        applied_end = (request.GET.get("applied_end") or "").strip()

        # 정렬 옵션 (latest/confidence)
        sort = (request.GET.get("sort") or "latest").strip()

        # 페이지당 건수: 너무 작거나 크게 오는 것을 제한
        per_page = request.GET.get("per_page") or "13"
        try:
            per_page = int(per_page)
        except ValueError:
            per_page = 13
        per_page = max(5, min(per_page, 100))

        # ----------------------
        # 2) 기본 QuerySet 구성
        # ----------------------
        qs = AiAnalysisResult.objects.all()

        # "정상 레코드만" 기본 리스트로 보여주기: confidence_score >= 0
        qs = qs.filter(confidence_score__gte=0)

        # 검색어(q): request_url 또는 domain에 포함되면 매치
        if q:
            qs = qs.filter(Q(request_url__icontains=q) | Q(domain__icontains=q))

        # ai_judgment UI에서 Harmful/Not harm 를 confidence_score 기준으로 분류
        if ai_judgment == "Harmful":
            qs = qs.filter(confidence_score__gte=50)
        elif ai_judgment == "Not harm":
            qs = qs.filter(confidence_score__lt=50)

        # is_checked: 문자열 true/false만 허용
        if is_checked in ("true", "false"):
            qs = qs.filter(is_checked=(is_checked == "true"))

        # checked_result / policy_type / admin 필터
        if checked_result:
            qs = qs.filter(checked_result=checked_result)
        if policy_type:
            qs = qs.filter(policy_type=policy_type)
        if admin:
            qs = qs.filter(admin__icontains=admin)

        # create_at 날짜 범위 (date 캐스팅 기반)
        if log_start:
            qs = qs.filter(create_at__date__gte=log_start)
        if log_end:
            qs = qs.filter(create_at__date__lte=log_end)

        # applied_at 날짜 범위
        if applied_start:
            qs = qs.filter(applied_at__date__gte=applied_start)
        if applied_end:
            qs = qs.filter(applied_at__date__lte=applied_end)

        # ----------------------
        # 2.5) request_url 중복 제거 (대표 1개만 남기기)
        # - MySQL에서도 동작하게 distinct-on 대신 Subquery 방식 사용
        # - 대표 조건:
        #   confidence_score DESC -> create_at DESC -> id DESC
        # - dup_count(동일 request_url 총건수)도 annotate
        # ----------------------
        base = qs  # (중복 제거 전) 필터가 모두 적용된 원본

        # request_url 별 대표 레코드 id를 1개 뽑는 서브쿼리
        rep_id_subq = (
            base.filter(request_url=OuterRef("request_url"))
                .order_by("-confidence_score", "-create_at", "-id")
                .values("id")[:1]
        )

        # request_url 그룹마다 rep_id를 annotate해서 rep_id 리스트를 만든 뒤
        rep_ids = (
            base.values("request_url")
                .annotate(rep_id=Subquery(rep_id_subq))
                .values("rep_id")
        )

        # 대표 id들만 다시 조회
        qs = AiAnalysisResult.objects.filter(id__in=Subquery(rep_ids))

        # dup_count: request_url이 같은 전체 개수
        dup_count_subq = (
            base.filter(request_url=OuterRef("request_url"))
                .values("request_url")
                .annotate(c=Count("id"))
                .values("c")[:1]
        )
        qs = qs.annotate(dup_count=Subquery(dup_count_subq))

        # ----------------------
        # 3) 정렬
        # ----------------------
        if sort == "confidence":
            qs = qs.order_by("-confidence_score", "-create_at")
        else:
            qs = qs.order_by("-create_at")

        # ----------------------
        # 4) 페이지네이션
        # ----------------------
        paginator = Paginator(qs, per_page)
        page_number = request.GET.get("page") or 1
        page_obj = paginator.get_page(page_number)

        # ----------------------
        # 5) 템플릿 컨텍스트
        # ----------------------
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
# 공통: 관리자 이름 추출
# - 로그인 사용자면 username
# - 아니면 "ADMIN"
# ============================================================
def _admin_name(request) -> str:
    u = getattr(request, "user", None)
    if u and getattr(u, "is_authenticated", False):
        return getattr(u, "username", None) or "ADMIN"
    return "ADMIN"


# ============================================================
# IGNORE 처리
# - 현재 row의 "domain" 전체에 IGNORE를 적용 (일괄 업데이트)
# - CSRF 보호 적용
# ============================================================
@method_decorator(csrf_protect, name="dispatch")
class AiIgnoreView(View):
    def post(self, request, pk):
        # pk는 테이블의 primary key(id)라고 가정
        row = get_object_or_404(AiAnalysisResult, pk=pk)
        admin_name = _admin_name(request)

        # 같은 도메인 전체에 대해 관리자 판단 반영
        updated = AiAnalysisResult.objects.filter(domain=row.domain).update(
            is_checked=True,
            checked_result="IGNORE",
            admin=admin_name,
            policy_type="",  # 운영DB 안정성: None 대신 빈 문자열
        )

        return JsonResponse({
            "ok": True,
            "domain": row.domain,
            "updated": updated,  # 영향받은 row 수
        })


# ============================================================
# 실시간 통계 API
# - KPI: FastAPI /status 우선
# - 차트:
#   (A) 최근 60초(초단위): 처리량(cnt), 응답속도(avg ai_latency_ms)
#   (B) 최근 24시간(시간단위): 처리량(cnt), 응답속도(avg ai_latency_ms)
# ============================================================
class AiStatusApiView(View):
    def get(self, request):
        # ----------------------------------------------------
        # 0) "현재 시각" 계산
        # - USE_TZ=True면 timezone.now()는 UTC aware
        # - localtime()으로 KST로 변환해 차트/필터 기준을 맞춤
        # - USE_TZ=False면 timezone.now()가 naive(로컬)라고 보고 그대로 사용
        # ----------------------------------------------------
        now_utc = timezone.now()
        now = timezone.localtime(now_utc) if getattr(settings, "USE_TZ", False) else now_utc

        # 오늘 범위(00:00:00 ~ 내일 00:00:00)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)

        # ----------------------------------------------------
        # 1) FastAPI 엔진 지표 조회 (KPI 우선 반영)
        # ----------------------------------------------------
        engine_ok, cpu_usage, memory_usage, rpm_fastapi, p95_fastapi, engine_err = _get_engine_usage()

        # ----------------------------------------------------
        # 2) KPI(오늘 총 분석 건수, RPM, 정확도, latency, cpu/mem)
        # ----------------------------------------------------
        total_today = AiAnalysisResult.objects.filter(
            create_at__gte=today_start,
            create_at__lt=tomorrow_start
        ).count()

        # RPM: FastAPI rpm_1m 우선, 실패 시 DB 기준 최근 1분 count로 대체
        last_minute = now - timedelta(minutes=1)
        rpm = rpm_fastapi if rpm_fastapi is not None else AiAnalysisResult.objects.filter(create_at__gte=last_minute).count()

        # 정확도(accuracy):
        # - reviewed: 관리자가 체크한(is_checked=True) 것들
        # - correct_count: ADD/IGNORE를 "정답/처리완료"로 보는 로직
        reviewed = AiAnalysisResult.objects.filter(is_checked=True)
        reviewed_count = reviewed.count()
        correct_count = reviewed.filter(checked_result__in=["ADD", "IGNORE"]).count()
        accuracy = round((correct_count / reviewed_count) * 100, 1) if reviewed_count else 0.0

        # Latency KPI: FastAPI p95 우선
        avg_latency_ms = p95_fastapi if (engine_ok and p95_fastapi is not None) else 0

        # ----------------------------------------------------
        # 3-A) 실시간 60초 차트 (초 단위)
        # - 처리량: 초당 Count
        # - 지연: 초당 Avg(ai_latency_ms) (0/NULL/음수 제외)
        # ----------------------------------------------------
        sec_end = now.replace(microsecond=0)
        sec_start = sec_end - timedelta(seconds=59)

        rt_qs = AiAnalysisResult.objects.filter(
            create_at__gte=sec_start,
            create_at__lt=sec_end + timedelta(seconds=1),
        )

        # TruncSecond는 상단에 import해도 되지만,
        # 여기서만 쓰면 "로컬 import"로 scope를 좁히는 것도 괜찮음
        from django.db.models.functions import TruncSecond

        # tzinfo:
        # - USE_TZ=True면 "현재 timezone(KST)" 기준으로 truncate
        # - USE_TZ=False면 naive이므로 tzinfo=None
        tz = timezone.get_current_timezone() if getattr(settings, "USE_TZ", False) else None

        rt_rows = (
            rt_qs
            .annotate(s=TruncSecond("create_at", tzinfo=tz))
            .values("s")
            .annotate(
                cnt=Count("id"),
                avg_latency=Coalesce(
                    Avg(
                        "ai_latency_ms",
                        filter=Q(ai_latency_ms__gt=0),  # 0/음수 제외
                        output_field=FloatField(),
                    ),
                    Value(0.0),
                ),
            )
            .order_by("s")
        )

        # "초(timestamp)" -> {cnt, avg_latency} 매핑
        rt_map = {r["s"]: r for r in rt_rows}

        # 60초를 "빈 구간 없이" 채워서 차트가 끊기지 않게 함
        rt_labels, rt_throughput, rt_latency = [], [], []
        for i in range(60):
            t = sec_start + timedelta(seconds=i)
            rt_labels.append(t.strftime("%H:%M:%S"))

            row = rt_map.get(t)
            if row:
                rt_throughput.append(int(row["cnt"] or 0))
                rt_latency.append(float(row["avg_latency"] or 0.0))
            else:
                rt_throughput.append(0)
                rt_latency.append(0.0)  # None 금지(Chart.js 끊김 방지)

        # ----------------------------------------------------
        # 3-B) 최근 24시간 차트 (시간 단위)
        # ----------------------------------------------------
        end_hour = now.replace(minute=0, second=0, microsecond=0)
        start_hour = end_hour - timedelta(hours=23)

        chart_qs = AiAnalysisResult.objects.filter(
            create_at__gte=start_hour,
            create_at__lt=end_hour + timedelta(hours=1),
        )

        hourly = (
            chart_qs
            .annotate(h=TruncHour("create_at", tzinfo=tz))
            .values("h")
            .annotate(
                cnt=Count("id"),
                avg_latency=Coalesce(
                    Avg(
                        "ai_latency_ms",
                        filter=Q(ai_latency_ms__gt=0),
                        output_field=FloatField(),
                    ),
                    Value(0.0),
                ),
            )
            .order_by("h")
        )

        hourly_map = {row["h"]: row for row in hourly}

        labels, throughput_series, latency_series = [], [], []
        for i in range(24):
            h = start_hour + timedelta(hours=i)
            labels.append(h.strftime("%H:%M"))

            row = hourly_map.get(h)
            if row:
                throughput_series.append(int(row["cnt"] or 0))
                latency_series.append(float(row["avg_latency"] or 0.0))
            else:
                throughput_series.append(0)
                latency_series.append(0.0)

        # ----------------------------------------------------
        # 4) 최근 오류 (confidence_score < 0)
        # - UI에 "최근 오류 10건" 표시 용도
        # ----------------------------------------------------
        recent_errors = list(
            AiAnalysisResult.objects
            .filter(confidence_score__lt=0)
            .order_by("-create_at")
            .values("create_at", "request_url", "confidence_score")[:10]
        )

        # ----------------------------------------------------
        # 5) 시스템 정보 (일단 TODO)
        # ----------------------------------------------------
        system_info = {
            "version": "v0.1 (TODO)",
            "developer": "Vision (TODO)",
        }

        # ----------------------------------------------------
        # 6) 최종 응답(JSON)
        # - ensure_ascii=False: 한글 깨짐 방지
        # ----------------------------------------------------
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
                # 24시간(시간단위)
                "labels": labels,
                "latency_series": latency_series,
                "throughput_series": throughput_series,

                # 60초(초단위)
                "rt_labels": rt_labels,
                "rt_latency_series": rt_latency,
                "rt_throughput_series": rt_throughput,

                # TODO(스파크라인/도넛에 쓰려면 실제 cpu/mem 시계열을 쌓아야 함)
                "cpu_spark": throughput_series,
                "mem_spark": throughput_series,
            },
            "recent_errors": recent_errors,
            "system_info": system_info,
        }, json_dumps_params={"ensure_ascii": False})


# ============================================================
# 관리자 "재검토" 버튼
# - 정책 reload가 아니라 엔진에게 "오류 재검토 작업"만 트리거
# - CSRF 보호 적용
# ============================================================
@method_decorator(csrf_protect, name="dispatch")
class AiRecheckErrorsView(View):
    def post(self, request):
        try:
            send_reload_signal("recheck_errors")
            return JsonResponse({"ok": True})
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=500)