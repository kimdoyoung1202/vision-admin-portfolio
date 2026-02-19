from django.contrib import admin
from .models import IntegratedDetectionLogs

# Register your models here.

@admin.register(IntegratedDetectionLogs)
class IntegratedDetectionLogsAdmin(admin.ModelAdmin) :
    
    #관리자 페이지에서 보여지는 컬럼 지정
    list_display = (
        "client_ip",        # 사용자 ip
        "detected_at",      # 탐지 시간
        "request_url",      # 요청 url  
        "domain",           # 도메인 주소
        "policy_id",        # 정책 id
        "http_method",      # http 메소드(post, get)
        "dst_port",         # 목적지 포트 번호
        "query_string",     # url 쿼리 스트링
        "create_at",        # 로그 추가 시간
    )
    
    #검색창 기준 입력창이 필요한 컬럼
    search_fields = (
        "request_url",
        "domain",
        "client_ip",
        "query_string",
    )
    
    # 검색창 기준 선택창이 필요한 컬럼
    list_filter = (
        "create_at",        # 탐지 기간/시간(달려 모양)
        "http_method",      # post 버튼 / get 버튼
    )
    
    # 탐지 기간/시간 기준으로 정렬
    ordering = ("create_at",)
    
    # 한 페이지에 30페이지 출력
    list_per_page = 30