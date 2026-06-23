"""Пароли и токены."""
from __future__ import annotations

import secrets

import bcrypt

# bcrypt напрямую (без passlib): passlib 1.7.x несовместим с bcrypt >= 4.1
# (ломается определение версии бэкенда). Хэши остаются стандартными $2b$ —
# совместимы со старыми, ранее созданными через passlib.


def hash_password(password: str) -> str:
    # bcrypt работает только с первыми 72 байтами — режем явно (valid_password это уже валидирует)
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        pw = password.encode("utf-8")[:72]
        return bcrypt.checkpw(pw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def new_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def valid_email(email: str) -> bool:
    """Лёгкая проверка без внешних зависимостей."""
    email = (email or "").strip()
    if len(email) > 254 or email.count("@") != 1:
        return False
    local, _, domain = email.partition("@")
    if not local or " " in email:
        return False
    labels = domain.split(".")
    # домен: минимум две непустые метки, TLD из букв длиной >= 2 (отсекает 'b.', '.com', 'a@b.')
    return len(labels) >= 2 and all(labels) and len(labels[-1]) >= 2 and labels[-1].isalpha()


def valid_password(password: str) -> tuple[bool, str]:
    """Пароль: 6..72 байта (bcrypt молча режет >72 — отклоняем явно)."""
    pw = password or ""
    if len(pw) < 6:
        return False, "Пароль должен быть не короче 6 символов."
    if len(pw.encode("utf-8")) > 72:
        return False, "Пароль слишком длинный (максимум 72 символа)."
    return True, ""


def safe_next(target: str, fallback: str = "/app") -> str:
    """Защита от open-redirect: разрешаем только локальные пути ('/...'),
    отклоняем абсолютные URL, протокол-относительные ('//evil') и обратные слэши."""
    t = (target or "").strip()
    if not t.startswith("/") or t.startswith("//") or t.startswith("/\\") or "\\" in t or ":" in t:
        return fallback
    return t
