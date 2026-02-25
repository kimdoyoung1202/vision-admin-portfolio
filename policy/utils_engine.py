# policy/utils_engine.py
import socket
from django.conf import settings

def send_reload_signal(message: str = "reload") -> None:
    host = getattr(settings, "ENGINE_RELOAD_HOST", "192.168.1.43")
    port = getattr(settings, "ENGINE_RELOAD_PORT", 5555)
    timeout = getattr(settings, "ENGINE_RELOAD_TIMEOUT", 2.0)

    data = (message + "\n").encode("utf-8")  # \n 붙이면 엔진에서 read-line 처리하기 쉬움

    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(data)
        


