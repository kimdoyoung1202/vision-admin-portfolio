from django.db import models


class PolicyUpdateHistory(models.Model):
    # 수정 이력 고유 ID
    id = models.AutoField(primary_key=True)

    # 원본 정책 테이블의 정책 ID
    policy_id = models.IntegerField()

    # 정책 이름
    policy_name = models.CharField(max_length=30)

    # 정책 타입 (예: DOMAIN, REGEX)
    policy_type = models.CharField(max_length=10)

    # 정책 URL 또는 정규표현식 내용
    content = models.TextField()

    # 정책 설명
    description = models.TextField(blank=True, null=True)

    # 처리 유형 (예: block, log)
    handling_type = models.CharField(max_length=10)

    # 수정 당시 정책 활성 여부
    is_active = models.BooleanField()

    # 정책 최초 등록자
    create_by = models.CharField(max_length=20)

    # 정책 최초 등록 시간
    create_at = models.DateTimeField()

    # 정책 수정한 관리자
    update_by = models.CharField(max_length=20)

    # 정책 수정 시간
    update_at = models.DateTimeField()

    class Meta:
        # 기존 DB 테이블을 그대로 사용하므로 Django가 테이블 생성/수정하지 않음
        managed = False

        # 연결할 실제 DB 테이블명
        db_table = "policy_update_history"