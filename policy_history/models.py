from django.db import models

# Create your models here.
class PolicyHistory(models.Model):

    id = models.AutoField(primary_key=True)
    
    policy_id = models.CharField(max_length=30)
    
    policy_name = models.CharField(max_length=30)
    
    policy_type = models.CharField(max_length=255)
    
    policy_value = models.TextField()
    
    description = models.TextField(null=True, blank=True)
    
    handling_type = models.CharField(max_length=10)
    
    is_active = models.BooleanField(default=True)
    
    create_by = models.CharField(max_length=20)
    
    create_at = models.DateTimeField(auto_now_add=True)
    
    delete_by = models.CharField(max_length=20)
    
    delete_at = models.DateTimeField()
    
    
    class Meta:
        managed = True
        db_table = 'policy_history'
