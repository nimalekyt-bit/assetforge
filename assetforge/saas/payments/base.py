"""Абстракция платёжного провайдера.

Любой провайдер реализует две вещи:
  - create_checkout: создать платёж и вернуть URL, куда отправить пользователя;
  - handle_webhook: разобрать уведомление провайдера и вернуть результат (paid/failed).

Активация подписки происходит централизованно в billing.py при статусе `paid`,
поэтому провайдеры не знают про модель пользователя — только про деньги.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CheckoutResult:
    redirect_url: str           # куда отправить пользователя для оплаты
    external_id: str = ""       # id платежа в системе провайдера
    message: str = ""


@dataclass
class WebhookResult:
    payment_id: int | None      # наш Payment.id (из metadata)
    status: str                 # paid | failed | ignored
    external_id: str = ""
    amount: float | None = None  # фактически оплаченная сумма (для сверки в mark_paid)
    currency: str = ""


class PaymentProvider:
    name: str = "base"

    def create_checkout(self, *, payment_id: int, plan: dict, amount: float,
                        currency: str, success_url: str, cancel_url: str) -> CheckoutResult:
        raise NotImplementedError

    def handle_webhook(self, *, headers: dict, body: bytes) -> WebhookResult:
        raise NotImplementedError

    @property
    def configured(self) -> bool:
        """Подключены ли реальные ключи (иначе провайдер в режиме заглушки)."""
        return True
