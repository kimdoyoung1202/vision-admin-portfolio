from django.db import models


class IntegratedDetectionLogs(models.Model):
    
    id = models.AutoField(primary_key=True)

    client_ip = models.CharField(max_length=15)
    
    request_url = models.TextField()
    
    domain = models.CharField(max_length=255)

    policy_name = models.CharField(max_length=30)
    
    policy_type = models.CharField(max_length=10)
    
    content = models.TextField()

    http_method = models.CharField(max_length=7)
    
    dst_port = models.IntegerField()
    
    query_string = models.TextField()
    
    create_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'integrated_detection_logs'