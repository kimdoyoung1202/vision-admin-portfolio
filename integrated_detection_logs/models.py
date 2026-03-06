from django.db import models

# Create your models here.
class IntegratedDetectionLogs(models.Model):

    id = models.AutoField(primary_key=True)

    client_ip = models.CharField(max_length=15)

    request_url = models.TextField()

    domain = models.CharField(max_length=255)
    
    policy_id = models.ForeignKey(
        'policy.Policy',
        to_field="policy_id",
        db_column='policy_id',
        on_delete=models.PROTECT,
    )

    http_method = models.CharField(max_length=7)

    dst_port = models.IntegerField()

    query_string = models.TextField()

    create_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'integrated_detection_logs'
