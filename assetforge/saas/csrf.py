"""CSRF-защита серверных форм (double-submit через сессию).

Токен хранится в подписанной session-cookie и дублируется скрытым полем формы.
На POST сверяем поле с сессией (constant-time). JSON-API (/api/*) не покрываем — там
от CSRF защищает SameSite=strict cookie и отсутствие form-сценария.
"""
from __future__ import annotations

import hmac
import secrets

from fastapi import Form, HTTPException, Request

FIELD = "csrf_token"


def get_token(request: Request) -> str:
    """Текущий CSRF-токен сессии (создаётся при первом обращении)."""
    try:
        tok = request.session.get("csrf")
    except Exception:  # noqa: BLE001 — нет SessionMiddleware (напр. в тестах ручек)
        return ""
    if not tok:
        tok = secrets.token_urlsafe(32)
        request.session["csrf"] = tok
    return tok


def verify(request: Request, token: str) -> bool:
    try:
        sess = request.session.get("csrf")
    except Exception:  # noqa: BLE001
        return False
    return bool(sess) and bool(token) and hmac.compare_digest(str(sess), str(token))


async def csrf_protect(request: Request, csrf_token: str = Form("")) -> None:
    """FastAPI-зависимость для POST-форм: бросает 403 при неверном/отсутствующем токене."""
    if not verify(request, csrf_token):
        raise HTTPException(403, "Сессия устарела или форма недействительна. "
                                 "Обновите страницу и попробуйте снова.")
