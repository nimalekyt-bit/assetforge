"""A/B фича-флаги: процентный выкат по стабильному хэшу пользователя."""
from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import FeatureFlag


def is_enabled(db: Session, name: str, user=None) -> bool:
    f = db.get(FeatureFlag, name)
    if not f or not f.enabled:
        return False
    if f.rollout >= 100:
        return True
    if f.rollout <= 0 or user is None:
        return False
    bucket = int(hashlib.sha1(f"{name}:{user.id}".encode()).hexdigest(), 16) % 100
    return bucket < f.rollout


def active_flags(db: Session, user) -> dict:
    return {f.name: is_enabled(db, f.name, user)
            for f in db.scalars(select(FeatureFlag)).all()}


def all_flags(db: Session) -> list:
    return db.scalars(select(FeatureFlag).order_by(FeatureFlag.name)).all()
