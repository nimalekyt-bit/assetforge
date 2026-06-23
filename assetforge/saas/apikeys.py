"""API-ключи: генерация, хранение (только хэш), проверка.

Формат ключа: af_<prefix8>_<secret32>. В БД храним префикс (для поиска) и sha256(полного ключа).
Полный ключ показываем пользователю один раз при создании.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ApiKey, User, utcnow


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_key(db: Session, user: User, name: str = "") -> tuple[ApiKey, str]:
    """Создать ключ. Возвращает (запись, полный_ключ_показать_один_раз)."""
    prefix = secrets.token_hex(4)            # 8 hex-символов
    secret = secrets.token_urlsafe(24)
    raw = f"af_{prefix}_{secret}"
    rec = ApiKey(user_id=user.id, name=(name or "").strip()[:80] or "ключ",
                 prefix=prefix, key_hash=_hash(raw))
    db.add(rec)
    db.flush()
    return rec, raw


def verify_key(db: Session, raw: str) -> User | None:
    """Найти пользователя по сырому ключу (если ключ активен)."""
    raw = (raw or "").strip()
    parts = raw.split("_", 2)
    if len(parts) != 3 or parts[0] != "af":
        return None
    prefix = parts[1]
    rec = db.scalar(select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.revoked.is_(False)))
    if not rec or not hmac.compare_digest(rec.key_hash, _hash(raw)):
        return None
    user = db.get(User, rec.user_id)
    if not user or not user.is_active:
        return None
    rec.last_used_at = utcnow()
    return user


def list_keys(db: Session, user: User) -> list[ApiKey]:
    return db.scalars(select(ApiKey).where(ApiKey.user_id == user.id)
                      .order_by(ApiKey.created_at.desc())).all()


def revoke(db: Session, user: User, key_id: int) -> bool:
    rec = db.get(ApiKey, key_id)
    if not rec or rec.user_id != user.id:
        return False
    rec.revoked = True
    return True
