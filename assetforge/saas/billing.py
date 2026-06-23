"""Биллинг: создание платежей, активация подписки, промокоды.

Провайдеры отвечают только за «движение денег»; активация тарифа происходит здесь,
централизованно, при подтверждённой оплате (mark_paid).
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import settings
from .models import Payment, PromoCode, PromoRedemption, User, utcnow
from .models import _aware as aware
from .payments import get_provider
from .payments.base import CheckoutResult
from .plans import get_plan, is_paid_plan, plan_exists


def price_for(plan: dict) -> tuple[float, str]:
    """Цена и валюта по настройке (RUB по умолчанию, USD если задано)."""
    if settings.currency.upper() == "RUB":
        return float(plan.get("price_rub", 0)), "RUB"
    return float(plan.get("price", 0)), settings.currency.upper()


def _extend_plan(user: User, plan_id: str, days: int) -> None:
    """Продлить/назначить тариф. Если тот же план ещё активен — добавляем к остатку."""
    now = utcnow()
    active_same = (user.plan_id == plan_id and user.plan_until and aware(user.plan_until) > now)
    base = aware(user.plan_until) if active_same else now
    user.plan_id = plan_id
    user.plan_until = base + timedelta(days=max(1, days))


REFERRAL_BONUS_DAYS = 14


def _reward_referrer(db: Session, user: User) -> None:
    """Наградить пригласившего при ПЕРВОЙ оплате приглашённого (однократно)."""
    if user.referral_rewarded or not user.referred_by_id:
        return
    referrer = db.get(User, user.referred_by_id)
    if referrer:
        _extend_plan(referrer, "pro", REFERRAL_BONUS_DAYS)
    user.referral_rewarded = True


def _consume_promo_use(db: Session, promo: PromoCode) -> bool:
    """Атомарно занять одно использование промокода с учётом max_uses (0 = безлимит).

    Условный UPDATE на уровне БД — защита от гонки (как в quota.try_consume).
    """
    res = db.execute(
        update(PromoCode)
        .where(PromoCode.id == promo.id, PromoCode.active.is_(True),
               (PromoCode.max_uses == 0) | (PromoCode.used_count < PromoCode.max_uses))
        .values(used_count=PromoCode.used_count + 1)
    )
    return res.rowcount > 0


# --- оплата -----------------------------------------------------------------

def create_payment(db: Session, user: User, plan_id: str,
                   provider_name: str | None = None, promo_code: str = ""):
    if not plan_exists(plan_id):
        raise HTTPException(400, "Неизвестный тариф.")
    plan = get_plan(plan_id)
    if not is_paid_plan(plan_id):
        raise HTTPException(400, "Бесплатный тариф не требует оплаты.")
    amount, currency = price_for(plan)
    code = ""
    promo: PromoCode | None = None
    if promo_code:
        promo = _validate_percent_promo(db, user, promo_code, plan_id)
        pct = min(100.0, max(0.0, promo.value))   # защита от value<0 или >100
        amount = max(0.0, round(amount * (1 - pct / 100.0), 2))
        code = promo.code

    period_days = int(plan.get("period_days", 30))

    # 100%-скидка (или нулевая цена) — активируем сразу, БЕЗ обращения к провайдеру
    if amount <= 0:
        if promo and not _consume_promo_use(db, promo):
            raise HTTPException(409, "Лимит использования промокода исчерпан.")
        pay = Payment(user_id=user.id, plan_id=plan_id, provider="promo", amount=0.0,
                      currency=currency, status="paid", promo_code=code,
                      period_days=period_days, paid_at=utcnow(), external_id="promo-100")
        db.add(pay)
        db.flush()
        _extend_plan(user, plan_id, period_days)
        if promo and not _already_redeemed(db, user, promo.code):
            db.add(PromoRedemption(user_id=user.id, code=promo.code))
        return pay, CheckoutResult(redirect_url=f"/account?paid={pay.id}",
                                   external_id=pay.external_id,
                                   message="Активировано по промокоду (100%).")

    provider = get_provider(provider_name)
    pay = Payment(user_id=user.id, plan_id=plan_id, provider=provider.name, amount=amount,
                  currency=currency, status="pending", promo_code=code,
                  period_days=period_days)
    db.add(pay)
    db.flush()

    base = settings.base_url.rstrip("/")
    checkout = provider.create_checkout(
        payment_id=pay.id, plan=plan, amount=amount, currency=currency,
        success_url=f"{base}/account?paid={pay.id}", cancel_url=f"{base}/pricing",
    )
    pay.external_id = checkout.external_id
    return pay, checkout


def mark_paid(db: Session, payment_id: int, *, expected_provider: str | None = None,
              expected_external_id: str | None = None,
              expected_amount: float | None = None) -> Payment | None:
    """Подтвердить оплату и активировать подписку (idempotent).

    При вызове из webhook передавайте expected_* — платёж активируется только если
    провайдер/external_id/сумма совпадают с записью (защита от подделки и перепутанного id).
    """
    pay = db.get(Payment, payment_id)
    if not pay or pay.status == "paid":
        return pay
    # сверка с реальным платёжным событием
    if expected_provider is not None and pay.provider != expected_provider:
        pay.status = "failed"
        return pay
    if expected_external_id is not None and pay.external_id != expected_external_id:
        pay.status = "failed"
        return pay
    if expected_amount is not None and round(float(pay.amount), 2) != round(float(expected_amount), 2):
        pay.status = "failed"
        return pay

    pay.status = "paid"
    pay.paid_at = utcnow()
    user = db.get(User, pay.user_id)
    _extend_plan(user, pay.plan_id, pay.period_days)
    _reward_referrer(db, user)
    if pay.promo_code:
        promo = db.scalar(select(PromoCode).where(PromoCode.code == pay.promo_code))
        if promo:
            _consume_promo_use(db, promo)
            if not _already_redeemed(db, user, promo.code):
                db.add(PromoRedemption(user_id=user.id, code=promo.code))
    return pay


# --- промокоды --------------------------------------------------------------

def _find_promo(db: Session, code: str) -> PromoCode | None:
    return db.scalar(select(PromoCode).where(PromoCode.code == (code or "").strip()))


def _already_redeemed(db: Session, user: User, code: str) -> bool:
    return bool(db.scalar(select(PromoRedemption).where(
        PromoRedemption.user_id == user.id, PromoRedemption.code == code)))


def _validate_percent_promo(db: Session, user: User, code: str, plan_id: str) -> PromoCode:
    promo = _find_promo(db, code)
    if not promo or not promo.is_valid():
        raise HTTPException(400, "Промокод недействителен или истёк.")
    if promo.kind != "percent":
        raise HTTPException(400, "Этот промокод не является скидкой к оплате.")
    if _already_redeemed(db, user, promo.code):
        raise HTTPException(409, "Вы уже использовали этот промокод.")
    return promo


def redeem_promo(db: Session, user: User, code: str) -> str:
    """Активировать промокод бесплатного доступа (free_days / grant_plan)."""
    promo = _find_promo(db, code)
    if not promo or not promo.is_valid():
        raise HTTPException(400, "Промокод недействителен или истёк.")
    if promo.kind == "percent":
        raise HTTPException(400, "Это промокод-скидка — введите его при оплате на странице тарифов.")
    if _already_redeemed(db, user, promo.code):
        raise HTTPException(409, "Вы уже использовали этот промокод.")
    if not plan_exists(promo.plan_id) or promo.plan_id == "free":
        raise HTTPException(400, "Промокод ссылается на недоступный тариф.")
    days = max(1, int(promo.value))
    if not _consume_promo_use(db, promo):
        raise HTTPException(409, "Лимит использования промокода исчерпан.")
    _extend_plan(user, promo.plan_id, days)
    db.add(PromoRedemption(user_id=user.id, code=promo.code))
    return f"Активирован тариф {get_plan(promo.plan_id)['title']} на {days} дн."
