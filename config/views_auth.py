import random
import smtplib
from email.mime.text import MIMEText

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.http import JsonResponse
from django.shortcuts import render, redirect

User = get_user_model()


def send_otp_email(to_email, otp_code):
    smtp_server = "smtp.gmail.com"
    smtp_port = 587

    gmail_id = "qudcks3655@gmail.com"
    gmail_password = "vhnq qciu bqgz qxpy"

    subject = "OTP 인증 코드"
    body = f"인증 코드는 {otp_code} 입니다."

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = gmail_id
    msg["To"] = to_email

    server = smtplib.SMTP(smtp_server, smtp_port)
    server.starttls()
    server.login(gmail_id, gmail_password)
    server.sendmail(gmail_id, to_email, msg.as_string())
    server.quit()


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def login_view(request):
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        next_url = request.POST.get("next") or "/"

        field_errors = {}

        if not username:
            field_errors["username"] = "아이디를 입력하세요."
        if not password:
            field_errors["password"] = "비밀번호를 입력하세요."

        if field_errors:
            if _is_ajax(request):
                return JsonResponse({
                    "ok": False,
                    "stage": "login",
                    "message": "입력값을 확인하세요.",
                    "field_errors": field_errors,
                }, status=400)

            return render(request, "auth/login.html", {
                "field_errors": field_errors,
                "username": username,
                "next": next_url,
            })

        user = authenticate(request, username=username, password=password)

        if user is None:
            if _is_ajax(request):
                return JsonResponse({
                    "ok": False,
                    "stage": "login",
                    "message": "아이디 또는 비밀번호가 틀렸습니다.",
                    "field_errors": {},
                }, status=400)

            return render(request, "auth/login.html", {
                "form_error": "아이디 또는 비밀번호가 틀렸습니다.",
                "username": username,
                "next": next_url,
            })

        if not user.email:
            if _is_ajax(request):
                return JsonResponse({
                    "ok": False,
                    "stage": "login",
                    "message": "이 계정에는 이메일이 없습니다.",
                    "field_errors": {},
                }, status=400)

            return render(request, "auth/login.html", {
                "form_error": "이 계정에는 이메일이 없습니다.",
                "username": username,
                "next": next_url,
            })

        otp_code = str(random.randint(100000, 999999))

        request.session["preauth_user_id"] = user.id
        request.session["otp_code"] = otp_code
        request.session["otp_email"] = user.email
        request.session["next_url"] = next_url

        send_otp_email(user.email, otp_code)

        if _is_ajax(request):
            return JsonResponse({
                "ok": True,
                "stage": "otp",
                "otp_required": True,
                "email": user.email,
                "message": "인증 코드가 이메일로 발송되었습니다.",
            })

        return redirect("otp")

    return render(request, "auth/login.html", {
        "next": request.GET.get("next", "/"),
    })


def otp_view(request):
    user_id = request.session.get("preauth_user_id")
    session_otp = request.session.get("otp_code")

    if not user_id:
        if _is_ajax(request):
            return JsonResponse({
                "ok": False,
                "message": "로그인 세션이 만료되었습니다. 다시 로그인해 주세요.",
            }, status=401)
        return redirect("login")

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        request.session.pop("preauth_user_id", None)
        request.session.pop("otp_code", None)
        request.session.pop("otp_email", None)
        request.session.pop("next_url", None)

        if _is_ajax(request):
            return JsonResponse({
                "ok": False,
                "message": "사용자 정보를 찾을 수 없습니다. 다시 로그인해 주세요.",
            }, status=401)
        return redirect("login")

    if request.method == "POST":
        otp = (request.POST.get("otp") or "").strip()

        if not otp:
            if _is_ajax(request):
                return JsonResponse({
                    "ok": False,
                    "stage": "otp",
                    "message": "OTP 코드를 입력하세요.",
                }, status=400)

            messages.error(request, "OTP 코드를 입력하세요.")
            return render(request, "auth/otp.html", {
                "email": request.session.get("otp_email"),
            })

        if otp == session_otp:
            login(request, user)

            redirect_url = request.session.get("next_url") or "/"

            request.session.pop("preauth_user_id", None)
            request.session.pop("otp_code", None)
            request.session.pop("otp_email", None)
            request.session.pop("next_url", None)

            if _is_ajax(request):
                return JsonResponse({
                    "ok": True,
                    "redirect_url": redirect_url,
                    "message": "인증이 완료되었습니다.",
                })

            return redirect(redirect_url)

        if _is_ajax(request):
            return JsonResponse({
                "ok": False,
                "stage": "otp",
                "message": "OTP 코드가 틀렸습니다.",
            }, status=400)

        messages.error(request, "OTP 코드가 틀렸습니다.")

    email = request.session.get("otp_email")
    return render(request, "auth/otp.html", {
        "email": email
    })


def logout_view(request):
    request.session.pop("preauth_user_id", None)
    request.session.pop("otp_code", None)
    request.session.pop("otp_email", None)
    request.session.pop("next_url", None)
    logout(request)
    return redirect("login")