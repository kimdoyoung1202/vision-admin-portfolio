from django.shortcuts import render

# Create your views here.
def ai_records(request):
    return render(request, "ai/ai_records.html")

def ai_status(request):
    return render(request, "ai/ai_status.html")