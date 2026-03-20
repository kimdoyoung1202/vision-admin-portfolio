# policy/utils_engine.py
import socket

from django.conf import settings


def send_reload_signal(message: str = "reload") -> None:
    """정책 엔진에 reload 신호를 전송한다."""
    host = getattr(settings, "ENGINE_RELOAD_HOST", "192.168.1.43")
    port = getattr(settings, "ENGINE_RELOAD_PORT", 5555)
    timeout = getattr(settings, "ENGINE_RELOAD_TIMEOUT", 2.0)

    payload = f"{message.strip() or 'reload'}\n".encode("utf-8")

    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(payload)
        


