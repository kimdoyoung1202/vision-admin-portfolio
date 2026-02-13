from django.contrib import admin
from .models import PolicyHistory

# Register your models here.

@admin.register(PolicyHistory)
class PolicyHistoryAdmin(admin.ModelAdmin) :
    
    #관리자 페이지에서 보여지는 컬럼 지정
    list_display = (
        "policy_id",        # 정책 아이디(ex: d0-001)
        "policy_name",      # 정책 이름(사용자 지정 : 네이버)
        "policy_type",      # 정책 타입(도메인/정규표현식)
        "content",          # url (도메인) / url 패턴 (정규표현식)
        "description",      # 정책 설명
        "handling_type",    # 처리 유형 (block/log //관리자 페이지에서는 한글로 표시)
        "is_active",        # 정책 적용 여부
        "create_by",        # 정책 추가한 사람의 id
        "create_at",        # 정책 생성 시간
        "delete_by",        # 정책 삭제한 사람의 id
        "delete_at",        # 정책 삭제 시간
    )
    
    # 검색창 기준 입력창이 필요한 컬럼
    search_fields = (
        "policy_id",
        "policy_name",
        "content",
        "delete_by",
    )
    
    # 검색창 기준 선택창이 필요한 컬럼
    list_filter = (
        "is_active",
        "handling_type",
        "delete_at",
    )
    
    # 정책 삭제 시간 기준으로 정렬
    ordering = ("-create_at",)
    
    list_per_page = 30