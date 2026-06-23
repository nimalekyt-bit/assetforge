"""Права доступа desktop-приложения (фримиум): гость vs вошедший пользователь.

Модель «Вариант C»:
  • Гость (без входа / просроченный офлайн-кэш) — жёсткие лимиты, чтобы стимулировать
    регистрацию: 256px, только PNG, без batch и без AI-фона.
  • Вошедший — лимиты его тарифа (free/pro/business), полученные из облака.

Состояние держится в процессе локального сервера и кэшируется на диск
(%LOCALAPPDATA%/AssetForge/session.json), чтобы вход переживал перезапуск.
Pro в офлайне действует ограниченное время (OFFLINE_GRACE_DAYS) — затем до повторной
онлайн-валидации права падают до гостевых.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from fastapi import HTTPException

from .. import cloud

# Лимиты гостя (без аккаунта). Сознательно скромные — апселл к регистрации/Pro.
GUEST_LIMITS = {
    "max_dimension": 256,
    "formats": ["png"],
    "batch_max_files": 1,
    "ai_background": False,
    "contact_sheet": False,
}

# Сколько Pro живёт в офлайне без переподтверждения тарифа.
OFFLINE_GRACE_DAYS = 7
_GRACE_SEC = OFFLINE_GRACE_DAYS * 24 * 3600

_lock = threading.Lock()
_state: dict = {
    "logged_in": False,
    "email": None,
    "name": None,
    "plan": "guest",
    "limits": dict(GUEST_LIMITS),
    "token": None,
    "validated_at": 0.0,
}


def _session_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "AssetForge" / "session.json"


def _guest_state() -> dict:
    return {"logged_in": False, "email": None, "name": None, "plan": "guest",
            "limits": dict(GUEST_LIMITS), "token": None, "validated_at": 0.0}


def set_logged_in(token: str, email: str, name: str | None, plan: str, limits: dict) -> None:
    with _lock:
        _state.update({
            "logged_in": True, "email": email, "name": name or "",
            "plan": plan, "limits": dict(limits or {}), "token": token,
            "validated_at": time.time(),
        })
        _save_locked()


def clear() -> None:
    with _lock:
        _state.update(_guest_state())
    try:
        _session_path().unlink(missing_ok=True)
    except OSError:
        pass


def load_cached() -> None:
    """Подтянуть сохранённую сессию с диска (без сети). Просроченный офлайн-кэш → гость."""
    p = _session_path()
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — битый файл → игнор
        return
    if not data.get("token"):
        return
    with _lock:
        _state.update({
            "logged_in": True,
            "email": data.get("email"),
            "name": data.get("name", ""),
            "plan": data.get("plan", "free"),
            "limits": dict(data.get("limits") or {}),
            "token": data.get("token"),
            "validated_at": float(data.get("validated_at", 0) or 0),
        })


def _save_locked() -> None:
    p = _session_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "email": _state["email"], "name": _state["name"], "plan": _state["plan"],
            "limits": _state["limits"], "token": _state["token"],
            "validated_at": _state["validated_at"],
        }), encoding="utf-8")
    except OSError:
        pass


def _effective_locked() -> tuple[str, dict, bool]:
    """(plan, limits, offline_expired) с учётом офлайн-грейса."""
    if not _state["logged_in"]:
        return "guest", dict(GUEST_LIMITS), False
    age = time.time() - float(_state.get("validated_at") or 0)
    if age > _GRACE_SEC:
        # офлайн-грейс истёк — до повторной онлайн-валидации режем до гостя
        return "guest", dict(GUEST_LIMITS), True
    return _state["plan"], dict(_state["limits"]), False


def current() -> dict:
    with _lock:
        plan, limits, expired = _effective_locked()
        return {
            "logged_in": _state["logged_in"] and not expired,
            "email": _state["email"],
            "name": _state["name"],
            "plan": plan,
            "limits": limits,
            "token": _state["token"],
            "offline_expired": expired,
        }


def status() -> dict:
    """Безопасный для UI снимок (без токена) + ссылки облака."""
    c = current()
    return {
        "desktop": True,
        "logged_in": c["logged_in"],
        "email": c["email"],
        "name": c["name"],
        "plan": c["plan"],
        "limits": c["limits"],
        "offline_expired": c["offline_expired"],
        "pricing_url": cloud.pricing_url(),
        "register_url": cloud.register_url(),
    }


# --- enforcement ------------------------------------------------------------

def _upsell(msg: str) -> str:
    c = current()
    if c["logged_in"]:
        return f"{msg} Оформите Pro: {cloud.pricing_url()}"
    return f"{msg} Войдите в аккаунт или зарегистрируйтесь — это бесплатно."


def enforce(cfg, batch_files: int = 1) -> None:
    """Проверить операцию против текущих прав. Бросает HTTPException(402) при превышении."""
    c = current()
    limits = c["limits"]

    sizes = [int(s) for s in (cfg.export.sizes or []) if int(s) > 0]
    max_dim = int(limits.get("max_dimension", 256))
    if sizes and max(sizes) > max_dim:
        raise HTTPException(402, _upsell(
            f"Размер до {max_dim}px в вашем режиме (запрошено {max(sizes)}px)."))

    allowed = set(limits.get("formats", ["png"]))
    bad = [f for f in (cfg.export.formats or []) if f.lower() not in allowed]
    if bad:
        raise HTTPException(402, _upsell(
            f"Форматы {', '.join(sorted(set(bad)))} недоступны в вашем режиме "
            f"(доступно: {', '.join(sorted(allowed))})."))

    if getattr(cfg.background, "mode", "") == "ai" and not limits.get("ai_background", False):
        raise HTTPException(402, _upsell("AI-удаление фона доступно на тарифе Pro."))

    if batch_files > int(limits.get("batch_max_files", 1)):
        raise HTTPException(402, _upsell(
            f"Пакетная обработка до {int(limits.get('batch_max_files', 1))} файлов в вашем режиме."))
