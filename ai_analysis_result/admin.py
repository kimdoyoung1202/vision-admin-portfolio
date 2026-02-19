from django.contrib import admin
from .models import AiAnalysisResult

# Register your models here.

@admin.register(AiAnalysisResult)
class AiAnalysisResultAdmin(admin.ModelAdmin) :
    
    # 관리자 페이지에 보여지는 컬럼 
    list_display = (
        "request_url",          # 요청받은 url
        "domain",               # 요청받은 url의 도메인 주소
        "confidence_score",     # 판단 결과 확률
        "is_checked",           # 정책 검토 여부    (관리자가 확인 했는지)
        "checked_result",       # 검토 결과         (관리자 검토 후 무시/ 정책 추가 등)
        "policy_type",          # 정책 타입         (정책으로 적용된 경우에만 기록)
        "admin",                # 정책 작성자의 id   (정책으로 적용된 경우에만 기록)
        "applied_at",           # 정책 적용 시간     (정책으로 적용된 경우에만 기롣)
        "create_at",            # ai결과가 로그로 적힌 시간
    )
    
    # 검색창 기준 입력창이 필요한 컬럼
    search_fields = (
        "request_url",
        "admin",
        "domain",
    )
    
    # 검색창 기준 선택창이 필요한 컬럼
    list_filter = (
        "create_at",        # ai 결과 생성 시간 (달력)
        "is_checked",       # 관리자 검토 여부 (선택창) 관리자 검토 선택시 checked_result(관리자 검토 결과) 활성화
        "checked_result",   # (토글)관리자 정책 추가 선택시 정책 타입(policy_type), 정책 추가 시간(applied_at), 정책 작성자(admin) 활성화
        "policy_type",      # 정책 타입 (도메인/정규표현식) 선택창
        "applied_at",       # 정책 추가 시간 (달력)
        
    )
    
    # 검토 여부, ai결과 로그기준으로 정렬
    ordering = ("is_checked", "create_at",)
    
    # 한 페이지에 30페이지 출력
    list_per_page = 30