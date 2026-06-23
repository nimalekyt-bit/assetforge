"""Настройки SaaS из переменных окружения (.env-совместимо).

Ничего секретного в коде. Платёжные ключи НЕ требуются для запуска — по умолчанию
активен «ручной» dev-провайдер, и вся цепочка подписки работает без реальных платежей.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Подхватить переменные из файла `.env` в корне проекта (без внешних зависимостей).

    Реальные переменные окружения имеют приоритет (setdefault). Формат: KEY=VALUE,
    строки с # — комментарии. Удобно для прод-настроек и строки подключения Supabase.
    """
    env_path = BASE.parent.parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _bool(key: str, default: bool = False) -> bool:
    return _env(key, str(default)).lower() in ("1", "true", "yes", "on")


DEFAULT_SECRET = "dev-insecure-change-me-in-prod"


class Settings:
    # секрет для подписи cookie-сессий. Если ASSETFORGE_SECRET не задан — генерируем
    # СЛУЧАЙНЫЙ per-process секрет (сессии не переживут рестарт, но подделать по
    # известному дефолту нельзя). В проде задавать через окружение обязательно.
    _secret_env: str = _env("ASSETFORGE_SECRET", "")
    secret_key_set: bool = bool(_secret_env)
    secret_key: str = _secret_env or secrets.token_urlsafe(48)

    # путь к SQLite (для прода можно подменить на Postgres-URL через ASSETFORGE_DB_URL)
    db_url: str = _env("ASSETFORGE_DB_URL", f"sqlite:///{(BASE.parent.parent / 'assetforge.db').as_posix()}")

    # платёжный провайдер: manual | stripe | yookassa
    payment_provider: str = _env("ASSETFORGE_PAYMENTS", "manual")
    # в dev «ручной» провайдер сразу подтверждает оплату (без админ-подтверждения)
    manual_autoconfirm: bool = _bool("ASSETFORGE_MANUAL_AUTOCONFIRM", True)

    # ключи провайдеров (пусто = не подключено, используется заглушка)
    stripe_secret: str = _env("STRIPE_SECRET_KEY", "")
    stripe_webhook_secret: str = _env("STRIPE_WEBHOOK_SECRET", "")
    yookassa_shop_id: str = _env("YOOKASSA_SHOP_ID", "")
    yookassa_secret: str = _env("YOOKASSA_SECRET_KEY", "")

    # email backend: console | smtp
    email_backend: str = _env("ASSETFORGE_EMAIL", "console")
    smtp_host: str = _env("SMTP_HOST", "")
    smtp_port: int = int(_env("SMTP_PORT", "587") or "587")
    smtp_user: str = _env("SMTP_USER", "")
    smtp_password: str = _env("SMTP_PASSWORD", "")
    email_from: str = _env("ASSETFORGE_EMAIL_FROM", "AssetForge <no-reply@assetforge.local>")

    # требовать подтверждение email перед использованием инструмента
    require_email_verification: bool = _bool("ASSETFORGE_REQUIRE_VERIFY", False)

    # первый администратор: права выдаются ТОЛЬКО если ASSETFORGE_ADMIN_EMAIL задан явно
    # (иначе на дефолтном публичном деплое любой бы зарегистрировался как админ).
    admin_email: str = _env("ASSETFORGE_ADMIN_EMAIL", "")
    admin_email_set: bool = bool(_env("ASSETFORGE_ADMIN_EMAIL"))

    # признак прод-окружения (для жёстких проверок безопасности на старте)
    environment: str = _env("ASSETFORGE_ENV", "dev")

    # публичный базовый URL (для ссылок в письмах и redirect'ов оплаты)
    base_url: str = _env("ASSETFORGE_BASE_URL", "http://127.0.0.1:8000")

    # валюта по умолчанию для отображения цен (RUB для русскоязычной аудитории)
    currency: str = _env("ASSETFORGE_CURRENCY", "RUB")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("prod", "production") or self.base_url.startswith("https://")

    @property
    def cookie_secure(self) -> bool:
        """Слать session-cookie только по HTTPS. По умолчанию — в проде; можно
        форсировать через ASSETFORGE_COOKIE_SECURE (актуально за TLS-прокси)."""
        return _bool("ASSETFORGE_COOKIE_SECURE", self.is_production)

    def validate_for_production(self) -> list[str]:
        """Проверки безопасности на старте. Возвращает список предупреждений;
        в проде критичные проблемы поднимают исключение."""
        problems: list[str] = []
        if not self.secret_key_set:
            problems.append("ASSETFORGE_SECRET не задан — используется случайный секрет "
                            "(сессии не переживут рестарт; задайте в проде).")
        if self.payment_provider == "manual" and self.is_production:
            problems.append("payment_provider=manual в проде — реальные платежи не принимаются.")
        if not self.admin_email_set and self.is_production:
            problems.append("ASSETFORGE_ADMIN_EMAIL не задан — некому администрировать.")
        if problems and self.is_production:
            raise RuntimeError("Небезопасная конфигурация для прода:\n  - " + "\n  - ".join(problems))
        return problems


settings = Settings()

