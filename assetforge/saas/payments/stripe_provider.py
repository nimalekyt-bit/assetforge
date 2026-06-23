"""Адаптер Stripe (структура готова, активируется при наличии ключей).

Без STRIPE_SECRET_KEY провайдер помечается как не сконфигурированный, и registry
откатывается на ручной режим. Чтобы включить реальные платежи:
  1) pip install stripe
  2) задать STRIPE_SECRET_KEY и STRIPE_WEBHOOK_SECRET
  3) раскомментировать вызовы stripe.* ниже.
"""
from __future__ import annotations

from ..config import settings
from .base import CheckoutResult, PaymentProvider, WebhookResult


class StripeProvider(PaymentProvider):
    name = "stripe"

    @property
    def configured(self) -> bool:
        return bool(settings.stripe_secret)

    def create_checkout(self, *, payment_id, plan, amount, currency,
                        success_url, cancel_url) -> CheckoutResult:
        if not self.configured:
            raise RuntimeError("Stripe не настроен: задайте STRIPE_SECRET_KEY.")
        # --- реальная интеграция (раскомментировать после установки stripe) ---
        # import stripe
        # stripe.api_key = settings.stripe_secret
        # session = stripe.checkout.Session.create(
        #     mode="subscription",
        #     line_items=[{"price_data": {
        #         "currency": currency.lower(),
        #         "product_data": {"name": f"AssetForge {plan['title']}"},
        #         "unit_amount": int(amount * 100),
        #         "recurring": {"interval": "month"},
        #     }, "quantity": 1}],
        #     success_url=success_url, cancel_url=cancel_url,
        #     metadata={"payment_id": str(payment_id)},
        # )
        # return CheckoutResult(redirect_url=session.url, external_id=session.id)
        raise RuntimeError("Stripe-интеграция не активирована (заглушка).")

    def handle_webhook(self, *, headers, body) -> WebhookResult:
        # БЕЗОПАСНОСТЬ: без проверки подписи НИКОГДА не помечаем платёж оплаченным.
        # Пока реальная интеграция закомментирована — webhook игнорируется, чтобы
        # неподписанный запрос не мог активировать подписку.
        if not self.configured or not settings.stripe_webhook_secret:
            return WebhookResult(payment_id=None, status="ignored")
        # --- реальная проверка подписи (раскомментировать с реальными ключами) ---
        # import stripe
        # event = stripe.Webhook.construct_event(
        #     body, headers.get("stripe-signature", ""), settings.stripe_webhook_secret)
        # if event["type"] == "checkout.session.completed":
        #     obj = event["data"]["object"]
        #     pid = int(obj["metadata"]["payment_id"])
        #     return WebhookResult(payment_id=pid, status="paid", external_id=obj["id"])
        return WebhookResult(payment_id=None, status="ignored")
