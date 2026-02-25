from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.urls import reverse


def login_view(request):
    # 이미 로그인 상태면 대시보드로
    if request.user.is_authenticated:
        return redirect("dashboard:home")

    next_url = request.GET.get("next") or request.POST.get("next") or ""
    context = {
        "next": next_url,
        "username": "",
        "form_error": "",
        "field_errors": {},
    }

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""

        context["username"] = username

        field_errors = {}
        if not username:
            field_errors["username"] = "아이디를 입력해 주세요."
        if not password:
            field_errors["password"] = "비밀번호를 입력해 주세요."
        context["field_errors"] = field_errors

        if field_errors:
            context["form_error"] = "입력값을 확인해 주세요."
            return render(request, "auth/login.html", context)

        user = authenticate(request, username=username, password=password)
        if user is None:
            context["form_error"] = "아이디 또는 비밀번호가 올바르지 않습니다."
            return render(request, "auth/login.html", context)

        login(request, user)

        request.session.set_expiry(0)

        # next 우선, 없으면 dashboard
        if next_url:
            return redirect(next_url)
        return redirect("dashboard:home")

    return render(request, "auth/login.html", context)


def logout_view(request):
    logout(request)
    return redirect("login")