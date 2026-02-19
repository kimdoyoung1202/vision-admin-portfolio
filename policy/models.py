from django.db import models

class Policy(models.Model):

    id = models.AutoField(primary_key=True)
    
    policy_id = models.CharField(max_length=30, unique=True)
    
    policy_name = models.CharField(max_length=30)
    
    policy_type = models.CharField(max_length=10)
    
    content = models.TextField()
    
    description = models.TextField(null=True, blank=True)
    
    handling_type = models.CharField(max_length=10)
    
    is_active = models.BooleanField(default=False)
    
    create_by = models.CharField(max_length=20)
    
    create_at = models.DateTimeField()
    
    
    class Meta:
        managed = False
        db_table = 'policy'
