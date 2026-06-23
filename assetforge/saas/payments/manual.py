"""Ручной dev-провайдер: вся цепочка подписки работает без реальных платежей.

create_checkout отправляет пользователя на внутреннюю страницу подтверждения
(/billing/manual/<payment_id>), где он жмёт «Оплатить (демо)». Это позволяет
протестировать апгрейд тарифа end-to-end, пока не подключены реальные ключи.
В проде с ASSETFORGE_MANUAL_AUTOCONFIRM=0 платёж ждёт подтверждения админом.
"""
from __future__ import annotations

from .base import CheckoutResult, PaymentProvider, WebhookResult


class ManualProvider(PaymentProvider):
    name = "manual"

    def create_checkout(self, *, payment_id, plan, amount, currency,
                        success_url, cancel_url) -> CheckoutResult:
        return CheckoutResult(
            redirect_url=f"/billing/manual/{payment_id}",
            external_id=f"manual-{payment_id}",
            message="Демо-оплата (реальные ключи не подключены).",
        )

    def handle_webhook(self, *, headers, body) -> WebhookResult:
        # у ручного провайдера нет внешних webhook'ов — подтверждение идёт через UI
        return WebhookResult(payment_id=None, status="ignored")

    @property
    def configured(self) -> bool:
        return True
