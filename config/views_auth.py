import random
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.shortcuts import render, redirect

import random
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.shortcuts import render, redirect

import smtplib
from email.mime.text import MIMEText


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

User = get_user_model()


import random
from django.contrib import messages
from django.contrib.auth import authenticate
from django.shortcuts import render, redirect


def login_view(request):

    if request.method == "POST":

        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:

            if not user.email:
                messages.error(request, "이 계정에는 이메일이 없습니다.")
                return redirect("login")

            otp_code = str(random.randint(100000, 999999))

            request.session["preauth_user_id"] = user.id
            request.session["otp_code"] = otp_code
            request.session["otp_email"] = user.email

            send_otp_email(user.email, otp_code)

            return redirect("otp")

        messages.error(request, "아이디 또는 비밀번호가 틀렸습니다.")

    return render(request, "auth/login.html")

def otp_view(request):

    user_id = request.session.get("preauth_user_id")
    session_otp = request.session.get("otp_code")

    if not user_id:
        return redirect("login")

    user = User.objects.get(id=user_id)

    if request.method == "POST":

        otp = request.POST.get("otp")

        if otp == session_otp:

            login(request, user)

            request.session.pop("preauth_user_id")
            request.session.pop("otp_code")
            request.session.pop("otp_email", None)

            return redirect("/")

        messages.error(request, "OTP 코드가 틀렸습니다.")

    email = request.session.get("otp_email")

    return render(request, "auth/otp.html", {
        "email": email
    })

def logout_view(request):
    request.session.pop("preauth_user_id", None)
    request.session.pop("otp_code", None)
    request.session.pop("next_url", None)
    logout(request)
    return redirect("login")