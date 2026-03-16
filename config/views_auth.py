import random
import smtplib
import threading
import time
from email.mime.text import MIMEText

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.http import JsonResponse
from django.shortcuts import render, redirect
from email.utils import formataddr

User = get_user_model()


def send_otp_email(to_email, otp_code):
    smtp_server = "smtp.gmail.com"
    smtp_port = 587

    gmail_id =  "qudcks3655@gmail.com"
    gmail_password = "udbd ozof thsk jmyt"

    subject = "OTP 인증 코드"
    body = f"인증 코드는 {otp_code} 입니다."

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("VISION", gmail_id))   # 여기만 변경
    msg["To"] = to_email

    server = None
    try:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(gmail_id, gmail_password)
        server.sendmail(gmail_id, [to_email], msg.as_string())
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass


def send_otp_email_async(to_email, otp_code):
    t = threading.Thread(
        target=send_otp_email,
        args=(to_email, otp_code),
        daemon=True,
    )
    t.start()


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def login_view(request):
    if request.method == "POST":
        storage = messages.get_messages(request)
        for _ in storage:
            pass
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
        request.session["otp_created_at"] = int(time.time())
        request.session["otp_last_sent_at"] = int(time.time())   
        request.session["otp_attempts"] = 0 

 
        send_otp_email_async(user.email, otp_code)

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
        request.session.pop("otp_created_at", None)

        if _is_ajax(request):
            return JsonResponse({
                "ok": False,
                "message": "사용자 정보를 찾을 수 없습니다. 다시 로그인해 주세요.",
            }, status=401)
        return redirect("login")

    if request.method == "POST":
        attempts = request.session.get("otp_attempts", 0)
        MAX_OTP_ATTEMPTS = 5

        if attempts + 1 >= MAX_OTP_ATTEMPTS:
            request.session.pop("preauth_user_id", None)
            request.session.pop("otp_code", None)
            request.session.pop("otp_email", None)
            request.session.pop("next_url", None)
            request.session.pop("otp_created_at", None)
            request.session.pop("otp_last_sent_at", None)
            request.session.pop("otp_attempts", None)

            if _is_ajax(request):
                return JsonResponse({
                    "ok": False,
                    "stage": "otp",
                    "message": "OTP 입력 가능 횟수를 초과했습니다. 다시 로그인해 주세요.",
                }, status=400)

            messages.error(request, "OTP 입력 가능 횟수를 초과했습니다. 다시 로그인해 주세요.")
            return redirect("login")
        
        otp_created_at = request.session.get("otp_created_at")
        OTP_EXPIRE_SECONDS = 120
        
        if not otp_created_at or int(time.time()) - otp_created_at > OTP_EXPIRE_SECONDS:
            if _is_ajax(request):
                return JsonResponse({
                    "ok": False,
                    "stage": "otp",
                    "expired": True,
                    "message": "OTP 유효시간이 만료되었습니다. 재전송해 주세요.",
                }, status=400)

            return render(request, "auth/otp.html", {
                "email": request.session.get("otp_email"),
                "expired": True,
                "form_error": "OTP 유효시간이 만료되었습니다. 재전송해 주세요.",
            })

        otp = (request.POST.get("otp") or "").strip()

        if not otp:
            if _is_ajax(request):
                return JsonResponse({
                    "ok": False,
                    "stage": "otp",
                    "message": "OTP 코드를 입력하세요.",
                }, status=400)

            return render(request, "auth/otp.html", {
                "email": request.session.get("otp_email"),
                "form_error": "OTP 코드를 입력하세요.",
            })

        if otp == session_otp:
            login(request, user)

            redirect_url = request.session.get("next_url") or "/"

            request.session.pop("preauth_user_id", None)
            request.session.pop("otp_code", None)
            request.session.pop("otp_email", None)
            request.session.pop("next_url", None)
            request.session.pop("otp_created_at", None)
            request.session.pop("otp_last_sent_at", None)
            request.session.pop("otp_attempts", None)

            if _is_ajax(request):
                return JsonResponse({
                    "ok": True,
                    "redirect_url": redirect_url,
                    "message": "인증이 완료되었습니다.",
                })

            return redirect(redirect_url)
        
        request.session["otp_attempts"] = attempts + 1
        remaining = MAX_OTP_ATTEMPTS - request.session["otp_attempts"]

        if _is_ajax(request):
            return JsonResponse({
                "ok": False,
                "stage": "otp",
                "message": f"OTP 코드가 틀렸습니다. 남은 횟수: {remaining}",
            }, status=400)

        return render(request, "auth/otp.html", {
            "email": request.session.get("otp_email"),
            "form_error": f"OTP 코드가 틀렸습니다. 남은 횟수: {remaining}",
        })

    email = request.session.get("otp_email")
    return render(request, "auth/otp.html", {
        "email": email
    })


def logout_view(request):
    request.session.pop("preauth_user_id", None)
    request.session.pop("otp_code", None)
    request.session.pop("otp_email", None)
    request.session.pop("next_url", None)
    request.session.pop("otp_created_at", None)
    request.session.pop("otp_last_sent_at", None)
    request.session.pop("otp_attempts", None)

    logout(request)
    return redirect("login")



def resend_otp_view(request):
    
    user_id = request.session.get("preauth_user_id")

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
        request.session.pop("otp_created_at", None)

        if _is_ajax(request):
            return JsonResponse({
                "ok": False,
                "message": "사용자 정보를 찾을 수 없습니다. 다시 로그인해 주세요.",
            }, status=401)
        return redirect("login")
    last_sent_at = request.session.get("otp_last_sent_at")
    RESEND_COOLDOWN_SECONDS = 30

    if last_sent_at and int(time.time()) - last_sent_at < RESEND_COOLDOWN_SECONDS:
        remaining = RESEND_COOLDOWN_SECONDS - (int(time.time()) - last_sent_at)

        if _is_ajax(request):
            return JsonResponse({
                "ok": False,
                "stage": "otp",
                "message": f"{remaining}초 후에 다시 재전송할 수 있습니다.",
            }, status=400)

        return render(request, "auth/otp.html", {
            "email": request.session.get("otp_email"),
            "form_error": f"{remaining}초 후에 다시 재전송할 수 있습니다.",
        })
    
    otp_code = str(random.randint(100000, 999999))

    request.session["otp_code"] = otp_code
    request.session["otp_email"] = user.email
    request.session["otp_created_at"] = int(time.time())
    request.session["otp_last_sent_at"] = int(time.time())
    request.session["otp_attempts"] = 0 
    send_otp_email_async(user.email, otp_code)

    if _is_ajax(request):
        return JsonResponse({
            "ok": True,
            "stage": "otp",
            "message": "새 인증 코드가 이메일로 발송되었습니다.",
        })

    messages.success(request, "새 인증 코드가 이메일로 발송되었습니다.")
    return redirect("otp")