"""Выбор активного платёжного провайдера по конфигу с откатом на ручной."""
from __future__ import annotations

from ..config import settings
from .base import PaymentProvider
from .manual import ManualProvider
from .stripe_provider import StripeProvider
from .yookassa_provider import YooKassaProvider

_PROVIDERS = {
    "manual": ManualProvider,
    "stripe": StripeProvider,
    "yookassa": YooKassaProvider,
}


def get_provider(name: str | None = None) -> PaymentProvider:
    """Вернуть провайдера по имени (или из настроек). Если реальные ключи не заданы —
    откатываемся на ручной режим, чтобы система оставалась работоспособной."""
    name = (name or settings.payment_provider or "manual").lower()
    provider = _PROVIDERS.get(name, ManualProvider)()
    if not provider.configured:
        return ManualProvider()
    return provider


def provider_status() -> dict:
    """Для админки: какие провайдеры подключены."""
    return {name: cls().configured for name, cls in _PROVIDERS.items()}
