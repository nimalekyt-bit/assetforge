"""Тесты новых фич: API-ключи, реферальная награда, выручка по месяцам."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from assetforge.saas import adminsvc, apikeys, auth, billing
from assetforge.saas.models import Base, utcnow


def make_session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)()


def test_api_key_lifecycle():
    db = make_session()
    u = auth.register(db, "k@b.com", "secret1")
    rec, raw = apikeys.create_key(db, u, "ci")
    assert raw.startswith("af_")
    assert apikeys.verify_key(db, raw).id == u.id
    assert apikeys.verify_key(db, "af_x_y") is None
    apikeys.revoke(db, u, rec.id)
    assert apikeys.verify_key(db, raw) is None


def test_api_key_blocked_user():
    db = make_session()
    u = auth.register(db, "k2@b.com", "secret1")
    _, raw = apikeys.create_key(db, u, "ci")
    u.is_active = False
    db.flush()
    assert apikeys.verify_key(db, raw) is None


def test_referral_reward_on_first_payment():
    db = make_session()
    inviter = auth.register(db, "inv@b.com", "secret1")
    invited = auth.register(db, "new@b.com", "secret1", ref_code=inviter.referral_code)
    assert invited.referred_by_id == inviter.id
    pay, _ = billing.create_payment(db, invited, "pro")
    billing.mark_paid(db, pay.id)
    assert inviter.effective_plan() == "pro"      # +14 дней Pro
    assert invited.referral_rewarded is True
    # повторная оплата не награждает второй раз
    until1 = inviter.plan_until
    pay2, _ = billing.create_payment(db, invited, "pro")
    billing.mark_paid(db, pay2.id)
    assert inviter.plan_until == until1


def test_revenue_series_length():
    db = make_session()
    auth.register(db, "r@b.com", "secret1")
    m = adminsvc.dashboard_metrics(db)
    assert len(m["revenue_series"]) == 12
    assert all("m" in d and "v" in d for d in m["revenue_series"])


def _run_all():
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t(); passed += 1; print(f"  PASS  {t.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1; print(f"  FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed из {len(tests)}")
    return failed == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if _run_all() else 1)
