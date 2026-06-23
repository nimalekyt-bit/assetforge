"""Тесты коммерческого слоя (регистрация, квоты, апгрейд, промокоды).

Работают напрямую с функциями на изолированной in-memory БД. Запуск:
  python -m tests.test_saas    (или pytest)
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from assetforge.saas import auth, billing, quota
from assetforge.saas.models import Base, PromoCode, User, utcnow


def make_session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)()


def test_register_and_authenticate():
    db = make_session()
    u = auth.register(db, "a@b.com", "secret1", "Alice")
    assert u.id and u.email == "a@b.com" and u.email_verified
    assert auth.authenticate(db, "a@b.com", "secret1") is not None
    assert auth.authenticate(db, "a@b.com", "wrong") is None


def test_register_rejects_bad_input():
    db = make_session()
    for email, pwd, exc in [("bad", "secret1", True), ("ok@b.com", "123", True)]:
        try:
            auth.register(db, email, pwd)
            assert False, "ожидали ошибку"
        except HTTPException:
            assert exc


def test_duplicate_email():
    db = make_session()
    auth.register(db, "dup@b.com", "secret1")
    try:
        auth.register(db, "dup@b.com", "secret1")
        assert False
    except HTTPException as e:
        assert e.status_code == 409


def test_quota_blocks_oversize_and_format():
    db = make_session()
    u = auth.register(db, "q@b.com", "secret1")           # free
    # 2048 > 1024 на free
    try:
        quota.enforce_export(db, u, sizes=[2048], formats=["png"])
        assert False
    except HTTPException as e:
        assert e.status_code == 402 and "1024" in e.detail
    # svg недоступен на free
    try:
        quota.enforce_export(db, u, sizes=[256], formats=["svg"])
        assert False
    except HTTPException as e:
        assert e.status_code == 402


def test_quota_monthly_limit():
    db = make_session()
    u = auth.register(db, "lim@b.com", "secret1")
    rec = quota.get_usage(db, u)
    rec.exports = 20                                       # лимит free = 20
    try:
        quota.enforce_export(db, u, sizes=[256], formats=["png"], count=1)
        assert False
    except HTTPException as e:
        assert e.status_code == 402 and "лимит" in e.detail.lower()


def test_upgrade_flow_unlocks_pro():
    db = make_session()
    u = auth.register(db, "up@b.com", "secret1")
    assert u.effective_plan() == "free"
    pay, checkout = billing.create_payment(db, u, "pro")
    assert pay.status == "pending" and checkout.redirect_url.endswith(str(pay.id))
    billing.mark_paid(db, pay.id)
    assert u.effective_plan() == "pro"
    # теперь 2048 и svg разрешены
    quota.enforce_export(db, u, sizes=[2048], formats=["png", "svg"])   # не бросает


def test_mark_paid_idempotent():
    db = make_session()
    u = auth.register(db, "idem@b.com", "secret1")
    pay, _ = billing.create_payment(db, u, "pro")
    billing.mark_paid(db, pay.id)
    until1 = u.plan_until
    billing.mark_paid(db, pay.id)        # повторно — не должно продлевать снова
    assert u.plan_until == until1


def test_promo_percent_discount():
    db = make_session()
    db.add(PromoCode(code="HALF", kind="percent", value=50, plan_id="pro"))
    db.flush()
    u = auth.register(db, "promo@b.com", "secret1")
    base_amount = billing.price_for(billing.get_plan("pro"))[0]
    pay, _ = billing.create_payment(db, u, "pro", promo_code="HALF")
    assert abs(pay.amount - base_amount * 0.5) < 0.01 and pay.promo_code == "HALF"


def test_promo_free_days_grants_plan():
    db = make_session()
    db.add(PromoCode(code="FREE30", kind="free_days", value=30, plan_id="pro"))
    db.flush()
    u = auth.register(db, "fd@b.com", "secret1")
    msg = billing.redeem_promo(db, u, "FREE30")
    assert "Pro" in msg and u.effective_plan() == "pro"
    # повторно тем же пользователем — нельзя
    try:
        billing.redeem_promo(db, u, "FREE30")
        assert False
    except HTTPException as e:
        assert e.status_code == 409


def test_try_consume_atomic_quota():
    db = make_session()
    u = auth.register(db, "tc@b.com", "secret1")          # free cap 20
    assert quota.try_consume(db, u, 18) is True
    assert quota.try_consume(db, u, 5) is False            # 18+5 > 20 — отказ
    assert quota.try_consume(db, u, 2) is True             # ровно до 20
    assert quota.get_usage(db, u).exports == 20
    quota.refund(db, u, 5)
    assert quota.get_usage(db, u).exports == 15


def test_no_admin_without_configured_email():
    # без явного ASSETFORGE_ADMIN_EMAIL никто не должен получать админку
    from assetforge.saas.config import settings
    assert settings.admin_email_set is False
    db = make_session()
    u = auth.register(db, "admin@assetforge.local", "secret1")
    assert u.is_admin is False


def test_plan_expiry_falls_back_to_free():
    db = make_session()
    u = auth.register(db, "exp@b.com", "secret1")
    u.plan_id = "pro"
    u.plan_until = utcnow() - timedelta(days=1)   # истёк вчера
    assert u.effective_plan() == "free"


# --- раннер ---------------------------------------------------------------

def _run_all():
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t(); passed += 1; print(f"  PASS  {t.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed из {len(tests)}")
    return failed == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if _run_all() else 1)
