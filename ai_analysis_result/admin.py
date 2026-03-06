from django.contrib import admin
from .models import AiAnalysisResult


@admin.register(AiAnalysisResult)
class AiAnalysisResultAdmin(admin.ModelAdmin):

    # 관리자 페이지 목록에서 보여줄 컬럼
    # create_at은 현재 모델에 없으므로 last_seen으로 변경
    list_display = (
        "request_url",       # 요청 URL
        "domain",            # 도메인
        "confidence_score",  # AI 판단 확률
        "hit_count",         # 중복 누적 건수
        "is_checked",        # 관리자 검토 여부
        "checked_result",    # 관리자 검토 결과
        "policy_type",       # 정책 타입
        "admin",             # 정책 작성자
        "applied_at",        # 정책 적용 시간
        "last_seen",         # 마지막 발생 시간
    )

    # 검색창 기준 입력 필드
    search_fields = (
        "request_url",
        "admin",
        "domain",
    )

    # 우측 필터 선택창
    list_filter = (
        "is_checked",
        "checked_result",
        "policy_type",
    )

    # 정렬 기준
    # create_at 대신 last_seen 사용
    ordering = ("is_checked", "-last_seen",)

    # 관리자 목록 한 페이지 표시 수
    list_per_page = 30