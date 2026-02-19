from django.shortcuts import render

# Create your views here.
def logs_list(request):
    return render(request, "logs/logs_list.html")