from django.contrib import admin
from .models import AiAnalysisResult

# Register your models here.

@admin.register(AiAnalysisResult)
class AiAnalysisResultAdmin(admin.ModelAdmin) :
    
    list_display = ()