"""Адаптер ЮKassa (структура готова, активируется при наличии ключей).

Для РФ-аудитории/карт МИР. Без YOOKASSA_SHOP_ID/SECRET — режим заглушки.
Включение реальных платежей:
  1) pip install yookassa
  2) задать YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY
  3) раскомментировать вызовы ниже.
"""
from __future__ import annotations

from ..config import settings
from .base import CheckoutResult, PaymentProvider, WebhookResult


class YooKassaProvider(PaymentProvider):
    name = "yookassa"

    @property
    def configured(self) -> bool:
        return bool(settings.yookassa_shop_id and settings.yookassa_secret)

    def create_checkout(self, *, payment_id, plan, amount, currency,
                        success_url, cancel_url) -> CheckoutResult:
        if not self.configured:
            raise RuntimeError("ЮKassa не настроена: задайте YOOKASSA_SHOP_ID/SECRET.")
        # --- реальная интеграция (раскомментировать после установки yookassa) ---
        # from yookassa import Configuration, Payment as YKPayment
        # Configuration.account_id = settings.yookassa_shop_id
        # Configuration.secret_key = settings.yookassa_secret
        # p = YKPayment.create({
        #     "amount": {"value": f"{amount:.2f}", "currency": currency},
        #     "confirmation": {"type": "redirect", "return_url": success_url},
        #     "capture": True,
        #     "description": f"AssetForge {plan['title']}",
        #     "metadata": {"payment_id": str(payment_id)},
        # })
        # return CheckoutResult(redirect_url=p.confirmation.confirmation_url, external_id=p.id)
        raise RuntimeError("ЮKassa-интеграция не активирована (заглушка).")

    def handle_webhook(self, *, headers, body) -> WebhookResult:
        # БЕЗОПАСНОСТЬ: без подтверждённой подписи/проверки платежа в API ЮKassa
        # webhook не активирует подписку (иначе любой POST дал бы Pro бесплатно).
        if not self.configured:
            return WebhookResult(payment_id=None, status="ignored")
        # --- реальный разбор + проверка статуса через API (раскомментировать с ключами) ---
        # event = json.loads(body)
        # obj = event["object"]
        # # ОБЯЗАТЕЛЬНО перепроверить статус платежа запросом к ЮKassa по obj["id"]
        # pid = int(obj["metadata"]["payment_id"])
        # status = "paid" if obj["status"] == "succeeded" else "failed"
        # return WebhookResult(payment_id=pid, status=status, external_id=obj["id"])
        return WebhookResult(payment_id=None, status="ignored")
