"""Фоновые задачи AssetForge (запуск по cron/планировщику).

Примеры:
    python -m assetforge.saas.tasks reminders     # письма об окончании подписки
    python -m assetforge.saas.tasks cleanup        # (зарезервировано)

`reminders` шлёт письмо тем, у кого подписка заканчивается примерно через 3 дня
(окно в 1 день — при ежедневном запуске каждый получит одно письмо).
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from .config import settings
from .db import session_scope
from .email import send_email
from ..logging_setup import get_logger
from .models import User, _aware, utcnow

log = get_logger("tasks")


def send_expiry_reminders(days: int = 3) -> int:
    """Письма о скором окончании платной подписки. Возвращает число отправленных."""
    sent = 0
    with session_scope() as db:
        now = utcnow()
        lo, hi = now + timedelta(days=days - 1), now + timedelta(days=days)
        users = db.scalars(
            select(User).where(User.plan_id != "free", User.plan_until.is_not(None))
        ).all()
        for u in users:
            pu = _aware(u.plan_until)
            if lo < pu <= hi and u.auto_renew:
                try:
                    send_email(u.email, "Подписка AssetForge скоро закончится",
                               f"Здравствуйте!\n\nВаша подписка «{u.plan_id}» действует до "
                               f"{pu:%d.%m.%Y}. Продлите её, чтобы не потерять доступ к Pro-функциям:\n"
                               f"{settings.base_url}/pricing\n\nЕсли продление не нужно — просто "
                               f"проигнорируйте письмо.")
                    sent += 1
                except Exception as exc:  # noqa: BLE001
                    log.warning("не удалось отправить напоминание %s: %s", u.email, exc)
    log.info("Отправлено напоминаний: %s", sent)
    return sent


def main() -> None:
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "reminders"
    if cmd == "reminders":
        print("Отправлено напоминаний:", send_expiry_reminders())
    else:
        print(f"Неизвестная команда: {cmd}")


if __name__ == "__main__":
    main()
