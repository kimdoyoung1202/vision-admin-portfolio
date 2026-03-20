from django.db import models


# AI 분석 결과 테이블 모델
# 운영 DB의 ai_analysis_result 테이블을 그대로 조회한다.
class AiAnalysisResult(models.Model):
    id = models.AutoField(primary_key=True)

    # 사용자가 요청한 전체 URL
    request_url = models.TextField()

    # 요청 URL에서 추출한 도메인
    domain = models.CharField(max_length=255)

    # 해당 URL이 마지막으로 탐지된 시각
    last_seen = models.DateTimeField()

    # AI 판단 점수
    # 오류 레코드는 -1 값으로 저장한다.
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2)

    # 동일 URL 누적 탐지 횟수
    hit_count = models.IntegerField(default=1)

    # 관리자 검토 여부
    is_checked = models.BooleanField(default=False)

    # 관리자 검토 결과
    # 예: ADD, IGNORE
    checked_result = models.CharField(max_length=10, null=True, blank=True)

    # 적용된 정책 타입
    # 예: DOMAIN, REGEX
    policy_type = models.CharField(max_length=30, null=True, blank=True)

    # 처리한 관리자 계정명
    admin = models.CharField(max_length=20, null=True, blank=True)

    # 정책이 실제 반영된 시각
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # 운영 중인 실제 테이블을 사용하므로 마이그레이션 대상에서 제외한다.
        managed = False
        db_table = "ai_analysis_result"