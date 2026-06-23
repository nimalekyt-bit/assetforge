"""Метеринг использования и enforcement лимитов тарифа."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from .models import UsageRecord, User
from .plans import plan_limits


def current_period(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def get_usage(db: Session, user: User, period: str | None = None) -> UsageRecord:
    period = period or current_period()
    rec = db.scalar(
        select(UsageRecord).where(UsageRecord.user_id == user.id, UsageRecord.period == period)
    )
    if not rec:
        rec = UsageRecord(user_id=user.id, period=period, exports=0)
        db.add(rec)
        db.flush()
    return rec


def usage_summary(db: Session, user: User) -> dict:
    limits = plan_limits(user.effective_plan())
    rec = get_usage(db, user)
    cap = limits.get("exports_per_month", 0)
    return {
        "plan": user.effective_plan(),
        "period": rec.period,
        "exports_used": rec.exports,
        "exports_limit": cap,
        "exports_left": max(0, cap - rec.exports),
    }


def enforce_export(db: Session, user: User, *, sizes: list[int], formats: list[str],
                   batch_files: int = 1, ai: bool = False, count: int = 1) -> None:
    """Проверить лимиты ПЕРЕД экспортом. Бросает 402/403 с понятным сообщением.

    count — сколько экспортов спишется (напр. число объектов/файлов).
    """
    plan = user.effective_plan()
    limits = plan_limits(plan)
    sizes = [int(s) for s in (sizes or []) if int(s) > 0]   # отсекаем мусор/отрицательные

    # 1) фичи плана
    if ai and not limits.get("ai_background", False):
        raise HTTPException(402, _upgrade("AI-удаление фона доступно на тарифе Pro."))
    max_dim = limits.get("max_dimension", 1024)
    if sizes and max(sizes) > max_dim:
        raise HTTPException(402, _upgrade(f"Размер до {max_dim}px на вашем тарифе. "
                                          f"Запрошено {max(sizes)}px."))
    allowed = set(limits.get("formats", []))
    bad = [f for f in formats if f not in allowed]
    if bad:
        raise HTTPException(402, _upgrade(f"Форматы {', '.join(bad)} недоступны на вашем тарифе."))
    if batch_files > limits.get("batch_max_files", 1):
        raise HTTPException(402, _upgrade(f"Batch до {limits.get('batch_max_files', 1)} файлов "
                                          f"на вашем тарифе."))

    # 2) месячная квота экспортов
    rec = get_usage(db, user)
    cap = limits.get("exports_per_month", 0)
    if rec.exports + count > cap:
        raise HTTPException(402, _upgrade(
            f"Исчерпан лимит экспортов ({rec.exports}/{cap} в этом месяце)."))


def try_consume(db: Session, user: User, count: int = 1, period: str | None = None) -> bool:
    """Атомарно списать `count` экспортов в пределах месячной квоты.

    Возвращает True, если квота позволила (списание выполнено), иначе False.
    Условный UPDATE на уровне БД защищает от гонки при параллельных экспортах.
    """
    period = period or current_period()
    cap = plan_limits(user.effective_plan()).get("exports_per_month", 0)
    get_usage(db, user, period)   # гарантируем существование строки
    res = db.execute(
        update(UsageRecord)
        .where(UsageRecord.user_id == user.id, UsageRecord.period == period,
               UsageRecord.exports + count <= cap)
        .values(exports=UsageRecord.exports + count)
    )
    return res.rowcount > 0


def refund(db: Session, user: User, count: int = 1, period: str | None = None) -> None:
    """Вернуть ранее списанные экспорты в ТОТ ЖЕ период, в котором списывали."""
    period = period or current_period()
    new_value = UsageRecord.exports - count
    db.execute(
        update(UsageRecord)
        .where(UsageRecord.user_id == user.id, UsageRecord.period == period)
        # переносимый clamp >= 0 (func.max(0,..) ломается на Postgres)
        .values(exports=case((new_value < 0, 0), else_=new_value))
    )


def _upgrade(msg: str) -> str:
    return f"{msg} Перейдите на Pro: /pricing"
