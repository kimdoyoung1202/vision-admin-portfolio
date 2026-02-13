from django.contrib import admin
from .models import Policy

# Register your models here.

@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin) :
    
    # 관리자 페이지에 보여지는 컬럼 
    list_display = (
        "policy_id",        # 정책 아이디(ex: do-001)
        "policy_name",      # 정책 이름 ( 사용자 지정 : 네이버)
        "policy_type",      # 정책 타입 (도메인/정규표현식)
        "content",          # url (도메인) / url 패턴 (정규표현식)  
        "is_active",        # 정책 적용 여부 (true : 적용 /false : 미적용)
        "handling_type",    # 처리 유형 (block/log //관리자 페이지에서는 한글로 표시)
        "created_by",       # 정책 추가한 사람의 id
        "create_at",        # 정책 생성 시간
        "description"       # 정책 설명
        )
    
    # 검색창 기준 입력창이 필요한 컬럼
    search_fields = (
        "policy_id", 
        "policy_name",
        "content",
        "create_by",
        )
    
    # 검색창 기준 선택창이 필요한 컬럼
    list_filter = (
        "policy_type",
        "is_active",
        "handling_type",
        "create_at",
    )
    
    # 정책 생성 시간 기준으로 정렬
    ordering = ("-create_at",)
    
    #상세 페이지로 들어가지 않고, 목록(리스트) 화면에서 바로 데이터를 수정하고 저장할 수 있게 해주는 설정 (토글/선택창)
    list_editable = (
        "is_active",
        "handling_type",
    )
    
    list_per_page = 30