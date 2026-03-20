from django.db import models


class Policy(models.Model):
    # 정책 고유 ID
    id = models.AutoField(primary_key=True)

    # 정책명
    policy_name = models.CharField(max_length=30)

    # 정책 타입
    policy_type = models.CharField(max_length=10)

    # 정책 대상 값(URL, 도메인, 정규식 등)
    content = models.TextField()

    # 정책 설명
    description = models.TextField(null=True, blank=True)

    # 처리 유형
    handling_type = models.CharField(max_length=10)

    # 활성 여부
    is_active = models.BooleanField(default=False)

    # 등록자 ID
    create_by = models.CharField(max_length=20)

    # 등록 일시
    create_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "policy"