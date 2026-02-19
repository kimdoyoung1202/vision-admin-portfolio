from django.db import models

# Create your models here.
class AiAnalysisResult(models.Model):

    id = models.AutoField(primary_key=True)
    
    request_url = models.TextField()
    
    domain = models.CharField(max_length=255)
    
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2)
    
    is_checked = models.BooleanField(default=False)
    
    checked_result = models.CharField(max_length=10, null=True, blank=True)
    
    policy_type = models.CharField(max_length=30, null=True, blank=True)
    
    admin = models.CharField(max_length=20, null=True, blank=True)
    
    applied_at = models.DateTimeField(null=True, blank=True)
    
    create_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'ai_analysis_result'
