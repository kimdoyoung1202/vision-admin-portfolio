from django.db import models


class PolicyUpdateHistory(models.Model):
    
    id = models.AutoField(primary_key=True)
    
    policy_id = models.IntegerField()

    policy_name = models.CharField(max_length=30)
    
    policy_type = models.CharField(max_length=10)
    
    content = models.TextField()
    
    description = models.TextField(blank=True, null=True)
    
    handling_type = models.CharField(max_length=10)
    
    is_active = models.BooleanField()

    create_by = models.CharField(max_length=20)
    
    create_at = models.DateTimeField()

    update_by = models.CharField(max_length=20)
    
    update_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "policy_update_history"