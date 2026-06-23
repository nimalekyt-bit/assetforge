"""Облачная аутентификация desktop-приложения (выдача и валидация токена тарифа).

Desktop логинится по email+паролю и получает подписанный токен (itsdangerous) +
текущий тариф с лимитами. Дальше периодически валидирует токен, чтобы отлавливать
смену/окончание тарифа. Эндпоинты публичные (у desktop нет cookie-сессии).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from . import auth, ratelimit
from .config import settings
from .db import get_db
from .models import User
from .plans import plan_limits

router = APIRouter()

TOKEN_MAX_AGE = 60 * 60 * 24 * 30      # 30 дней
_SALT = "assetforge-desktop-auth"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=_SALT)


def _entitlement(user: User) -> dict:
    plan = user.effective_plan()
    return {"email": user.email, "name": user.name or "", "plan": plan,
            "limits": plan_limits(plan)}


@router.post("/api/desktop/auth")
def desktop_auth(request: Request, payload: dict = None, db: Session = Depends(get_db)) -> JSONResponse:
    payload = payload or {}
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""

    if not ratelimit.allowed(request, "desktop_auth", 10, 300):
        return JSONResponse({"ok": False, "error": "Слишком много попыток. Подождите несколько минут."})

    user = auth.authenticate(db, email, password)
    if not user:
        return JSONResponse({"ok": False, "error": "Неверный email или пароль."})
    if settings.require_email_verification and not user.email_verified:
        return JSONResponse({"ok": False, "error": "Подтвердите email, чтобы войти."})

    token = _serializer().dumps({"uid": user.id})
    return JSONResponse({"ok": True, "token": token, **_entitlement(user)})


@router.post("/api/desktop/validate")
def desktop_validate(payload: dict = None, db: Session = Depends(get_db)) -> JSONResponse:
    payload = payload or {}
    token = payload.get("token") or ""
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return JSONResponse({"ok": False})
    user = db.get(User, data.get("uid"))
    if not user:
        return JSONResponse({"ok": False})
    # перевыпускаем токен (продлеваем срок) + отдаём актуальный тариф
    fresh = _serializer().dumps({"uid": user.id})
    return JSONResponse({"ok": True, "token": fresh, **_entitlement(user)})
