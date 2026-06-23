"""Rate-limit по (бакет, IP) поверх kvstore.

С Redis работает корректно между воркерами/инстансами; без него — в памяти процесса.
Семантика: фиксированное окно `window` секунд, не более `limit` попыток.
"""
from __future__ import annotations

from fastapi import Request

from ..kvstore import backend


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def allowed(request: Request, bucket: str, limit: int, window: float) -> bool:
    """True, если в текущем окне `window` сек ещё не превышен лимит `limit` для этого IP."""
    ip = client_ip(request)
    key = f"rl:{bucket}:{ip}"
    try:
        count = backend().incr_window(key, window)
    except Exception:  # noqa: BLE001 — сбой бэкенда не должен блокировать вход
        return True
    return count <= limit
