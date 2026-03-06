import re
from django.conf import settings
from django.shortcuts import redirect


EXEMPT_URLS = [re.compile(settings.LOGIN_URL.lstrip("/"))]
if hasattr(settings, "LOGIN_EXEMPT_URLS"):
    EXEMPT_URLS += [re.compile(expr) for expr in settings.LOGIN_EXEMPT_URLS]


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info.lstrip("/")

        # 로그인 안했으면 모든 페이지 차단
        if not request.user.is_authenticated:
            if not any(url.match(path) for url in EXEMPT_URLS):
                return redirect(f"{settings.LOGIN_URL}?next=/{path}")

        return self.get_response(request)