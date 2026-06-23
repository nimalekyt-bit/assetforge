"""Тесты управления аккаунтом и админ-сервисов (на изолированной in-memory БД).
Запуск: python -m tests.test_admin (или pytest)."""
from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from assetforge.saas import adminsvc, auth, billing
from assetforge.saas.models import Base, User, utcnow


def make_session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)()


def test_change_password():
    db = make_session()
    u = auth.register(db, "a@b.com", "secret1")
    ok, _ = auth.change_password(db, u, "wrong", "newpass1")
    assert not ok
    ok, _ = auth.change_password(db, u, "secret1", "123")          # слишком короткий
    assert not ok
    ok, _ = auth.change_password(db, u, "secret1", "newpass1")
    assert ok and auth.authenticate(db, "a@b.com", "newpass1") is not None


def test_delete_account():
    db = make_session()
    u = auth.register(db, "d@b.com", "secret1")
    auth.delete_account(db, u)
    assert auth.authenticate(db, "d@b.com", "secret1") is None


def test_blocked_user_denied():
    db = make_session()
    u = auth.register(db, "bl@b.com", "secret1")
    u.is_active = False
    try:
        auth.require_user(user=u)
        assert False, "ожидали 403"
    except HTTPException as e:
        assert e.status_code == 403


def test_cancel_resume_renew():
    db = make_session()
    u = auth.register(db, "c@b.com", "secret1")
    assert u.auto_renew is True
    u.auto_renew = False
    assert u.auto_renew is False


def test_settings_get_set():
    db = make_session()
    assert adminsvc.get_bool(db, "registration_open") is True       # дефолт
    adminsvc.set_setting(db, "registration_open", "0")
    assert adminsvc.get_bool(db, "registration_open") is False
    adminsvc.set_setting(db, "maintenance_mode", "1")
    assert adminsvc.get_bool(db, "maintenance_mode") is True


def test_audit_log():
    db = make_session()
    admin = auth.register(db, "adm@b.com", "secret1"); admin.is_admin = True
    adminsvc.audit(db, admin, "user.grant_plan", "user:1", "pro +30д")
    from assetforge.saas.models import AuditLog
    from sqlalchemy import select
    rows = db.scalars(select(AuditLog)).all()
    assert len(rows) == 1 and rows[0].action == "user.grant_plan" and rows[0].admin_email == "adm@b.com"


def test_dashboard_metrics():
    db = make_session()
    u = auth.register(db, "m1@b.com", "secret1")
    p = auth.register(db, "m2@b.com", "secret1")
    p.plan_id = "pro"; p.plan_until = utcnow() + timedelta(days=10)
    db.flush()
    m = adminsvc.dashboard_metrics(db)
    assert m["total_users"] == 2 and m["paid_users"] == 1 and m["mrr"] > 0
    assert 0 <= m["conversion"] <= 100


def test_totp_roundtrip():
    from assetforge.saas import totp
    s = totp.new_secret()
    # сгенерируем валидный код тем же алгоритмом
    import base64, hmac, hashlib, struct, time
    key = base64.b32decode(s + "=" * (-len(s) % 8), casefold=True)
    d = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    o = d[-1] & 15
    code = str((struct.unpack(">I", d[o:o + 4])[0] & 0x7FFFFFFF) % 1000000).zfill(6)
    assert totp.verify(s, code)
    assert not totp.verify(s, "000001") or code == "000001"


def test_rbac_roles():
    from assetforge.saas.models import User
    def mk(role):
        return User(email="x", password_hash="x", role=role, is_active=True, is_admin=(role != "user"))
    assert auth.require_admin(user=mk("support")).role == "support"
    for bad_role in ("support",):
        try:
            auth.require_writer(user=mk(bad_role)); assert False
        except HTTPException as e:
            assert e.status_code == 403
    assert auth.require_writer(user=mk("admin")).role == "admin"
    try:
        auth.require_superadmin(user=mk("admin")); assert False
    except HTTPException as e:
        assert e.status_code == 403


def test_plan_overrides():
    from assetforge.saas import plans
    plans.apply_overrides({"pro": {"price_rub": 1234, "limits": {"max_dimension": 3000}}})
    try:
        assert plans.get_plan("pro")["price_rub"] == 1234
        assert plans.plan_limits("pro")["max_dimension"] == 3000
        # базовые форматы не затёрты deep-merge'ем
        assert "png" in plans.plan_limits("pro")["formats"]
    finally:
        plans.apply_overrides({})


def test_analytics_shape():
    db = make_session()
    auth.register(db, "an@b.com", "secret1")
    a = adminsvc.analytics(db, 30)
    assert set(a) >= {"signups", "revenue", "plan_distribution", "payment_status"}
    assert len(a["revenue"]) == 12 and len(a["signups"]) == 30


def test_login_event_and_logs():
    db = make_session()
    u = auth.register(db, "le@b.com", "secret1")
    adminsvc.record_login(db, u, u.email, "1.2.3.4", True, "login")
    adminsvc.record_login(db, None, "bad@b.com", "5.6.7.8", False, "login")
    from assetforge.saas.models import LoginEvent
    from sqlalchemy import select
    rows = db.scalars(select(LoginEvent)).all()
    assert len(rows) == 2 and any(r.success for r in rows) and any(not r.success for r in rows)


def test_recent_logs_ring():
    from assetforge.logging_setup import get_logger, recent_logs
    get_logger("test").warning("проверка кольцевого буфера 12345")
    assert any("12345" in r["msg"] for r in recent_logs(50))


def test_notify_noop_without_config():
    db = make_session()
    # без настроек telegram/webhook — просто ничего не делает (не падает)
    adminsvc.notify(db, "title", "text")


def test_feature_flags():
    from assetforge.saas import flags
    from assetforge.saas.models import FeatureFlag
    db = make_session()
    u = auth.register(db, "ff@b.com", "secret1")
    db.add(FeatureFlag(name="on100", rollout=100, enabled=True))
    db.add(FeatureFlag(name="off", rollout=100, enabled=False))
    db.add(FeatureFlag(name="zero", rollout=0, enabled=True))
    db.flush()
    assert flags.is_enabled(db, "on100", u) is True
    assert flags.is_enabled(db, "off", u) is False
    assert flags.is_enabled(db, "zero", u) is False
    assert flags.is_enabled(db, "missing", u) is False


def test_ip_matches():
    assert adminsvc.ip_matches("10.0.0.5", ["10.0.0.0/24"]) is True
    assert adminsvc.ip_matches("10.0.1.5", ["10.0.0.0/24"]) is False
    assert adminsvc.ip_matches("203.0.113.7", ["203.0.113.7"]) is True
    assert adminsvc.ip_matches("1.2.3.4", []) is False


def test_announcement_schedule():
    from datetime import timedelta
    db = make_session()
    future = (utcnow() + timedelta(days=1)).isoformat()
    past = (utcnow() - timedelta(days=1)).isoformat()
    adminsvc.set_announcement(db, "привет", start=future)     # ещё не началось
    assert adminsvc.current_announcement() == ""
    adminsvc.set_announcement(db, "привет", start=past)        # уже идёт
    assert adminsvc.current_announcement() == "привет"
    adminsvc.set_announcement(db, "")                          # сброс


def test_version_stat_and_cohorts():
    db = make_session()
    adminsvc.record_version(db, "0.1.0")
    adminsvc.record_version(db, "0.1.0")
    from assetforge.saas.models import VersionStat
    assert db.get(VersionStat, "0.1.0").count == 2
    auth.register(db, "ch@b.com", "secret1")
    rows = adminsvc.cohorts(db, 12)
    assert rows and all({"month", "signups", "paying", "conversion"} <= set(r) for r in rows)


def test_force_logout_session_epoch():
    from assetforge.saas import auth as a
    db = make_session()
    u = auth.register(db, "fl@b.com", "secret1")

    class Req:
        def __init__(self, sess): self.session = sess
    assert a.current_user(Req({"uid": u.id, "epoch": 0}), db).id == u.id
    u.session_epoch = 1                                       # принудительный разлогин
    assert a.current_user(Req({"uid": u.id, "epoch": 0}), db) is None
    assert a.current_user(Req({"uid": u.id, "epoch": 1}), db).id == u.id


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
