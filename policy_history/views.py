from django.shortcuts import render

# Create your views here.
def history_list(request):
    return render(request, "policy_history/history_list.html")