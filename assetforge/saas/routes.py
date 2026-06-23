"""HTTP-маршруты SaaS: страницы, аутентификация, биллинг, промокоды, админка."""
from __future__ import annotations

import csv
import io as _io
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from . import auth, billing, ratelimit
from . import adminsvc
from . import apikeys
from . import flags
from . import totp
from .config import settings
from .csrf import csrf_protect, get_token as _csrf_token, verify as csrf_verify
from .db import get_db
from .models import (AuditLog, DesktopRelease, FeatureFlag, LoginEvent, Payment, PromoCode,
                     PromoRedemption, UsageRecord, User, VersionStat, WebhookEvent, utcnow)
from .payments.registry import get_provider, provider_status
from .plans import all_plans, get_plan, is_paid_plan, plan_exists, load_plans
from .quota import get_usage, usage_summary
from .security import safe_next

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
router = APIRouter()

# демо-режим самоподтверждения оплаты: только manual-провайдер, вне прода, с включённым флагом
DEMO_PAY = (settings.payment_provider == "manual" and settings.manual_autoconfirm
            and not settings.is_production)


def _page(request: Request, name: str, user: User | None, **ctx) -> HTMLResponse:
    ctx.setdefault("csrf_token", _csrf_token(request))
    ctx.setdefault("announcement", adminsvc.current_announcement())
    try:
        ctx.setdefault("impersonating", bool(request.session.get("imp_admin")))
    except Exception:  # noqa: BLE001
        ctx.setdefault("impersonating", False)
    return TEMPLATES.TemplateResponse(request, name, {"user": user, **ctx})


# --- публичные страницы -----------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def landing(request: Request, user: User | None = Depends(auth.current_user)):
    return _page(request, "landing.html", user, plans=all_plans(), currency=settings.currency)


@router.get("/pricing", response_class=HTMLResponse)
def pricing(request: Request, user: User | None = Depends(auth.current_user), message: str = ""):
    return _page(request, "pricing.html", user, plans=all_plans(), currency=settings.currency,
                 provider=settings.payment_provider, demo=DEMO_PAY, message=message)


# статические информационные страницы (оферта, политика, контакты, FAQ)

@router.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request, user: User | None = Depends(auth.current_user)):
    return _page(request, "terms.html", user)


@router.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request, user: User | None = Depends(auth.current_user)):
    return _page(request, "privacy.html", user)


@router.get("/offer", response_class=HTMLResponse)
def offer_page(request: Request, user: User | None = Depends(auth.current_user)):
    return _page(request, "offer.html", user)


@router.get("/contacts", response_class=HTMLResponse)
def contacts_page(request: Request, user: User | None = Depends(auth.current_user)):
    return _page(request, "contacts.html", user)


@router.get("/faq", response_class=HTMLResponse)
def faq_page(request: Request, user: User | None = Depends(auth.current_user)):
    return _page(request, "faq.html", user)


# --- регистрация / вход -----------------------------------------------------

@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, next: str = "/app", ref: str = "",
                  user: User | None = Depends(auth.current_user),
                  db: Session = Depends(get_db)):
    if user:
        return RedirectResponse("/account", 303)
    if not adminsvc.get_bool(db, "registration_open"):
        return _page(request, "info_message.html", None, title="Регистрация закрыта", ok=False,
                     message="Регистрация временно приостановлена. Загляните позже.")
    return _page(request, "register.html", None, next=safe_next(next), ref=ref)


@router.post("/register")
def register_submit(request: Request, db: Session = Depends(get_db),
                    email: str = Form(...), password: str = Form(...),
                    name: str = Form(""), next: str = Form("/app"), ref: str = Form(""),
                    _csrf: None = Depends(csrf_protect)):
    nxt = safe_next(next)
    if not adminsvc.get_bool(db, "registration_open"):
        return _page(request, "register.html", None, next=nxt,
                     error="Регистрация временно приостановлена.")
    if not ratelimit.allowed(request, "register", 5, 300):
        return _page(request, "register.html", None, next=nxt,
                     error="Слишком много попыток. Повторите через несколько минут.")
    try:
        u = auth.register(db, email, password, name, ref_code=ref)
    except HTTPException as e:
        return _page(request, "register.html", None, error=e.detail, next=nxt, ref=ref)
    adminsvc.notify(db, "Новая регистрация AssetForge", u.email)
    # при включённой верификации — не пускаем сразу в инструмент, показываем «проверьте почту»
    if settings.require_email_verification and not u.email_verified:
        auth.login_session(request, u)
        return _page(request, "verify_notice.html", u, email=u.email)
    auth.login_session(request, u)
    return RedirectResponse(nxt, 303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/app", user: User | None = Depends(auth.current_user)):
    if user:
        return RedirectResponse("/account", 303)
    return _page(request, "login.html", None, next=safe_next(next))


@router.post("/login")
def login_submit(request: Request, db: Session = Depends(get_db),
                 email: str = Form(...), password: str = Form(...), next: str = Form("/app"),
                 _csrf: None = Depends(csrf_protect)):
    nxt = safe_next(next)
    if not ratelimit.allowed(request, "login", 8, 60):
        return _page(request, "login.html", None, next=nxt,
                     error="Слишком много попыток входа. Подождите минуту и попробуйте снова.")
    u = auth.authenticate(db, email, password)
    ip = ratelimit.client_ip(request)
    if not u:
        adminsvc.record_login(db, None, email, ip, False)
        return _page(request, "login.html", None, error="Неверный email или пароль.", next=nxt)
    if not u.is_active:
        adminsvc.record_login(db, u, email, ip, False)
        return _page(request, "login.html", None, error="Аккаунт заблокирован.", next=nxt)
    if u.totp_enabled:
        request.session["pending_2fa"] = {"uid": u.id, "next": nxt}
        return RedirectResponse("/login/2fa", 303)
    adminsvc.record_login(db, u, email, ip, True)
    auth.login_session(request, u)
    return RedirectResponse(nxt, 303)


@router.get("/login/2fa", response_class=HTMLResponse)
def login_2fa_page(request: Request):
    if not request.session.get("pending_2fa"):
        return RedirectResponse("/login", 303)
    return _page(request, "two_factor.html", None)


@router.post("/login/2fa")
def login_2fa_submit(request: Request, db: Session = Depends(get_db),
                     code: str = Form(""), _csrf: None = Depends(csrf_protect)):
    pending = request.session.get("pending_2fa")
    if not pending:
        return RedirectResponse("/login", 303)
    if not ratelimit.allowed(request, "2fa", 8, 120):
        return _page(request, "two_factor.html", None, error="Слишком много попыток. Подождите.")
    u = db.get(User, pending.get("uid"))
    if not u or not totp.verify(u.totp_secret, code):
        adminsvc.record_login(db, u, getattr(u, "email", ""), ratelimit.client_ip(request), False, "2fa")
        return _page(request, "two_factor.html", None, error="Неверный код. Попробуйте ещё раз.")
    request.session.pop("pending_2fa", None)
    adminsvc.record_login(db, u, u.email, ratelimit.client_ip(request), True, "2fa")
    auth.login_session(request, u)
    return RedirectResponse(safe_next(pending.get("next", "/app")), 303)


@router.get("/logout")
def logout(request: Request):
    auth.logout_session(request)
    return RedirectResponse("/", 303)


@router.get("/verify", response_class=HTMLResponse)
def verify(request: Request, token: str = "", db: Session = Depends(get_db),
           user: User | None = Depends(auth.current_user)):
    ok = auth.verify_email(db, token)
    msg = "Email подтверждён ✓ Можно пользоваться инструментом." if ok else "Ссылка недействительна или уже использована."
    return _page(request, "info_message.html", user, title="Подтверждение email",
                 ok=ok, message=msg)


@router.post("/verify/resend")
def verify_resend(request: Request, db: Session = Depends(get_db),
                  user: User = Depends(auth.require_user_unverified),
                  _csrf: None = Depends(csrf_protect)):
    if ratelimit.allowed(request, "verify_resend", 5, 600):
        auth.resend_verification(db, user)
    return _page(request, "verify_notice.html", user, email=user.email,
                 resent=True)


# --- сброс пароля -----------------------------------------------------------

@router.get("/forgot", response_class=HTMLResponse)
def forgot_page(request: Request, user: User | None = Depends(auth.current_user)):
    return _page(request, "forgot.html", user)


@router.post("/forgot")
def forgot_submit(request: Request, db: Session = Depends(get_db), email: str = Form(...),
                  _csrf: None = Depends(csrf_protect)):
    if ratelimit.allowed(request, "forgot", 5, 600):
        auth.start_password_reset(db, email)
    # всегда одинаковый ответ — не раскрываем, существует ли аккаунт
    return _page(request, "info_message.html", None, title="Сброс пароля", ok=True,
                 message="Если такой email зарегистрирован, мы отправили на него ссылку для сброса пароля.")


@router.get("/reset", response_class=HTMLResponse)
def reset_page(request: Request, token: str = ""):
    return _page(request, "reset.html", None, token=token)


@router.post("/reset")
def reset_submit(request: Request, db: Session = Depends(get_db),
                 token: str = Form(""), password: str = Form(...),
                 _csrf: None = Depends(csrf_protect)):
    if not ratelimit.allowed(request, "reset", 10, 600):
        return _page(request, "reset.html", None, token=token,
                     error="Слишком много попыток. Повторите позже.")
    ok, msg = auth.reset_password(db, token, password)
    if not ok:
        return _page(request, "reset.html", None, token=token, error=msg)
    return _page(request, "info_message.html", None, title="Пароль изменён", ok=True, message=msg)


# --- личный кабинет ---------------------------------------------------------

@router.get("/account", response_class=HTMLResponse)
def account(request: Request, db: Session = Depends(get_db),
            user: User = Depends(auth.require_user), paid: str = ""):
    msg = "Оплата прошла, тариф активирован ✓" if paid else ""
    return _account_page(request, db, user, message=msg)


@router.post("/promo/redeem")
def promo_redeem(request: Request, db: Session = Depends(get_db),
                 user: User = Depends(auth.require_user), code: str = Form(...),
                 _csrf: None = Depends(csrf_protect)):
    def _account(**extra):
        payments = db.scalars(
            select(Payment).where(Payment.user_id == user.id).order_by(Payment.created_at.desc())
        ).all()
        return _page(request, "account.html", user, plan=get_plan(user.effective_plan()),
                     usage=usage_summary(db, user), payments=payments, **extra)

    if not ratelimit.allowed(request, "promo", 10, 600):
        return _account(error="Слишком много попыток. Повторите позже.")
    try:
        billing.redeem_promo(db, user, code)
    except HTTPException as e:
        return _account(error=e.detail)
    return RedirectResponse("/account", 303)


@router.post("/account/profile")
def account_profile(request: Request, db: Session = Depends(get_db),
                    user: User = Depends(auth.require_user), name: str = Form(""),
                    _csrf: None = Depends(csrf_protect)):
    auth.update_profile(db, user, name)
    return RedirectResponse("/account", 303)


@router.post("/account/password")
def account_password(request: Request, db: Session = Depends(get_db),
                     user: User = Depends(auth.require_user),
                     old_password: str = Form(...), new_password: str = Form(...),
                     _csrf: None = Depends(csrf_protect)):
    ok, msg = auth.change_password(db, user, old_password, new_password)
    return _account_page(request, db, user, **({"message": msg} if ok else {"error": msg}))


@router.post("/account/cancel")
def account_cancel(request: Request, db: Session = Depends(get_db),
                   user: User = Depends(auth.require_user),
                   _csrf: None = Depends(csrf_protect)):
    user.auto_renew = False
    return _account_page(request, db, user,
                         message="Продление отменено. Доступ сохранится до конца оплаченного периода.")


@router.post("/account/resume")
def account_resume(request: Request, db: Session = Depends(get_db),
                   user: User = Depends(auth.require_user),
                   _csrf: None = Depends(csrf_protect)):
    user.auto_renew = True
    return _account_page(request, db, user, message="Автопродление снова включено.")


@router.post("/account/delete")
def account_delete(request: Request, db: Session = Depends(get_db),
                   user: User = Depends(auth.require_user), password: str = Form(""),
                   _csrf: None = Depends(csrf_protect)):
    from .security import verify_password
    if not verify_password(password or "", user.password_hash):
        return _account_page(request, db, user, error="Для удаления подтвердите текущий пароль.")
    auth.delete_account(db, user)
    auth.logout_session(request)
    db.commit()
    return _page(request, "info_message.html", None, title="Аккаунт удалён", ok=True,
                 message="Ваш аккаунт и связанные данные удалены. Спасибо, что были с нами.")


@router.get("/account/2fa", response_class=HTMLResponse)
def account_2fa(request: Request, db: Session = Depends(get_db),
                user: User = Depends(auth.require_user)):
    if user.totp_enabled:
        return _page(request, "two_factor_setup.html", user, enabled=True)
    secret = request.session.get("totp_candidate") or totp.new_secret()
    request.session["totp_candidate"] = secret
    uri = totp.provisioning_uri(secret, user.email)
    return _page(request, "two_factor_setup.html", user, enabled=False,
                 secret=secret, uri=uri, qr=totp.qr_data_uri(uri))


@router.post("/account/2fa/enable")
def account_2fa_enable(request: Request, db: Session = Depends(get_db),
                       user: User = Depends(auth.require_user), code: str = Form(""),
                       _csrf: None = Depends(csrf_protect)):
    secret = request.session.get("totp_candidate")
    if not secret or not totp.verify(secret, code):
        uri = totp.provisioning_uri(secret or "", user.email) if secret else ""
        return _page(request, "two_factor_setup.html", user, enabled=False,
                     secret=secret, uri=uri, qr=totp.qr_data_uri(uri) if uri else None,
                     error="Неверный код. Отсканируйте QR и введите текущий код из приложения.")
    user.totp_secret, user.totp_enabled = secret, True
    request.session.pop("totp_candidate", None)
    return _account_page(request, db, user, message="Двухфакторная аутентификация включена.")


@router.post("/account/2fa/disable")
def account_2fa_disable(request: Request, db: Session = Depends(get_db),
                        user: User = Depends(auth.require_user), password: str = Form(""),
                        _csrf: None = Depends(csrf_protect)):
    from .security import verify_password
    if not verify_password(password or "", user.password_hash):
        return _account_page(request, db, user, error="Подтвердите паролем, чтобы отключить 2FA.")
    user.totp_enabled, user.totp_secret = False, ""
    return _account_page(request, db, user, message="Двухфакторная аутентификация отключена.")


def _account_page(request: Request, db: Session, user: User, **extra) -> HTMLResponse:
    from sqlalchemy import select as _select
    payments = db.scalars(
        _select(Payment).where(Payment.user_id == user.id).order_by(Payment.created_at.desc())
    ).all()
    if not user.referral_code:                       # бэкфилл для старых аккаунтов
        from .security import new_token
        user.referral_code = new_token(6)[:10]
    ref_link = f"{settings.base_url}/register?ref={user.referral_code}"
    return _page(request, "account.html", user, plan=get_plan(user.effective_plan()),
                 usage=usage_summary(db, user), payments=payments,
                 api_keys=apikeys.list_keys(db, user),
                 new_api_key=request.session.pop("new_api_key", None),
                 ref_link=ref_link, **extra)


@router.post("/account/apikeys/create")
def account_apikey_create(request: Request, db: Session = Depends(get_db),
                          user: User = Depends(auth.require_user), name: str = Form(""),
                          _csrf: None = Depends(csrf_protect)):
    if user.effective_plan() == "free":
        return _account_page(request, db, user, error="API-ключи доступны на платном тарифе.")
    _rec, raw = apikeys.create_key(db, user, name)
    db.commit()
    request.session["new_api_key"] = raw            # показать один раз
    return RedirectResponse("/account#api", 303)


@router.post("/account/apikeys/{key_id}/revoke")
def account_apikey_revoke(request: Request, key_id: int, db: Session = Depends(get_db),
                          user: User = Depends(auth.require_user), _csrf: None = Depends(csrf_protect)):
    apikeys.revoke(db, user, key_id)
    return RedirectResponse("/account#api", 303)


# --- биллинг ----------------------------------------------------------------

@router.post("/billing/checkout")
def checkout(request: Request, db: Session = Depends(get_db),
             user: User = Depends(auth.require_user),
             plan_id: str = Form(...), promo: str = Form(""),
             _csrf: None = Depends(csrf_protect)):
    try:
        pay, result = billing.create_payment(db, user, plan_id, promo_code=promo.strip())
    except HTTPException as e:
        return _page(request, "pricing.html", user, plans=all_plans(),
                     provider=settings.payment_provider, demo=DEMO_PAY, message=e.detail)
    return RedirectResponse(result.redirect_url, 303)


@router.get("/billing/manual/{payment_id}", response_class=HTMLResponse)
def manual_pay_page(request: Request, payment_id: int, db: Session = Depends(get_db),
                    user: User = Depends(auth.require_user)):
    pay = db.get(Payment, payment_id)
    if not pay or pay.user_id != user.id:
        raise HTTPException(404, "Платёж не найден.")
    return _page(request, "manual_pay.html", user, payment=pay, plan=get_plan(pay.plan_id),
                 demo=DEMO_PAY)


@router.post("/billing/manual/{payment_id}/confirm")
def manual_pay_confirm(request: Request, payment_id: int, db: Session = Depends(get_db),
                       user: User = Depends(auth.require_user),
                       _csrf: None = Depends(csrf_protect)):
    pay = db.get(Payment, payment_id)
    if not pay or pay.user_id != user.id:
        raise HTTPException(404, "Платёж не найден.")
    # самоподтверждение допустимо ТОЛЬКО в демо-режиме; иначе платёж ждёт админ-подтверждения
    if not DEMO_PAY:
        return RedirectResponse("/account", 303)
    billing.mark_paid(db, payment_id)
    adminsvc.notify(db, "Оплата получена (демо)", f"{user.email} · платёж #{payment_id}")
    return RedirectResponse(f"/account?paid={payment_id}", 303)


@router.post("/billing/webhook/{provider}")
async def billing_webhook(provider: str, request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    result = get_provider(provider).handle_webhook(headers=dict(request.headers), body=body)
    db.add(WebhookEvent(provider=provider, status=result.status,
                        payment_id=result.payment_id, external_id=result.external_id or "",
                        detail=f"amount={result.amount}" if result.amount is not None else ""))
    if result.status == "paid" and result.payment_id:
        # активируем ТОЛЬКО при совпадении провайдера/external_id/суммы (защита от подделки)
        billing.mark_paid(db, result.payment_id, expected_provider=provider,
                          expected_external_id=result.external_id or None,
                          expected_amount=result.amount)
        adminsvc.notify(db, "Оплата получена", f"{provider} · платёж #{result.payment_id}")
    return {"ok": True, "status": result.status}


# --- админка ----------------------------------------------------------------

ADMIN_PER_PAGE = 25


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db),
                    admin: User = Depends(auth.require_admin), message: str = ""):
    return _page(request, "admin.html", admin, m=adminsvc.dashboard_metrics(db),
                 providers=provider_status(), message=message, tab="dashboard")


@router.get("/admin/metrics.json")
def admin_metrics(db: Session = Depends(get_db), admin: User = Depends(auth.require_admin),
                  days: int = 30) -> JSONResponse:
    days = max(7, min(int(days or 30), 365))
    return JSONResponse(adminsvc.analytics(db, days))


# --- пользователи -----------------------------------------------------------

@router.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, db: Session = Depends(get_db),
                admin: User = Depends(auth.require_admin),
                q: str = "", plan: str = "", segment: str = "", page: int = 1):
    stmt = select(User)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.name.ilike(like)))
    if plan:
        stmt = stmt.where(User.plan_id == plan)
    now = utcnow()
    if segment == "paid":
        stmt = stmt.where(User.plan_id != "free", User.plan_until.is_not(None), User.plan_until > now)
    elif segment == "free":
        stmt = stmt.where(User.plan_id == "free")
    elif segment == "expiring":
        stmt = stmt.where(User.plan_id != "free", User.plan_until.is_not(None),
                          User.plan_until > now, User.plan_until <= now + timedelta(days=7))
    elif segment == "blocked":
        stmt = stmt.where(User.is_active.is_(False))
    elif segment == "staff":
        stmt = stmt.where(User.is_admin.is_(True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    pg = adminsvc.paginate(total, page, ADMIN_PER_PAGE)
    users = db.scalars(stmt.order_by(User.created_at.desc())
                       .offset(pg["offset"]).limit(pg["per"])).all()
    return _page(request, "admin_users.html", admin, users=users, pg=pg, q=q, plan=plan,
                 segment=segment, plans=load_plans(), tab="users")


@router.post("/admin/users/bulk")
def admin_users_bulk(request: Request, db: Session = Depends(get_db),
                     admin: User = Depends(auth.require_writer), action: str = Form(...),
                     ids: str = Form(""), plan_id: str = Form("pro"), days: int = Form(30),
                     _csrf: None = Depends(csrf_protect)):
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    users = db.scalars(select(User).where(User.id.in_(id_list))).all() if id_list else []
    n = 0
    for u in users:
        if u.id == admin.id:
            continue
        if action == "grant_plan" and plan_exists(plan_id) and plan_id != "free":
            billing._extend_plan(u, plan_id, max(1, int(days))); n += 1
        elif action == "reset_quota":
            get_usage(db, u).exports = 0; n += 1
        elif action == "block":
            u.is_active = False; n += 1
        elif action == "unblock":
            u.is_active = True; n += 1
    adminsvc.audit(db, admin, f"users.bulk.{action}", "", f"n={n}")
    return RedirectResponse(f"/admin/users?message={quote(f'Применено к {n} польз.')}", 303)


@router.get("/admin/users/{uid}", response_class=HTMLResponse)
def admin_user_detail(request: Request, uid: int, db: Session = Depends(get_db),
                      admin: User = Depends(auth.require_admin), message: str = "", error: str = ""):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Пользователь не найден.")
    payments = db.scalars(select(Payment).where(Payment.user_id == uid)
                          .order_by(Payment.created_at.desc())).all()
    redemptions = db.scalars(select(PromoRedemption).where(PromoRedemption.user_id == uid)
                             .order_by(PromoRedemption.created_at.desc())).all()
    usages = db.scalars(select(UsageRecord).where(UsageRecord.user_id == uid)
                        .order_by(UsageRecord.period.desc())).all()
    # таймлайн: платежи + промокоды + входы + действия админа над пользователем
    events = []
    events.append((u.created_at, "регистрация", u.email))
    for p in payments:
        events.append((p.paid_at or p.created_at, f"платёж {p.status}",
                       f"{p.plan_id} · {p.amount:.0f} {p.currency}"))
    for rdm in redemptions:
        events.append((rdm.created_at, "промокод", rdm.code))
    for le in db.scalars(select(LoginEvent).where(LoginEvent.user_id == uid)
                         .order_by(LoginEvent.created_at.desc()).limit(20)).all():
        events.append((le.created_at, "вход " + ("✓" if le.success else "✗"), f"{le.kind} · {le.ip}"))
    for a in db.scalars(select(AuditLog).where(AuditLog.target == f"user:{uid}")
                        .order_by(AuditLog.created_at.desc()).limit(20)).all():
        events.append((a.created_at, a.action, f"{a.admin_email} · {a.detail}"))
    timeline = sorted([e for e in events if e[0]], key=lambda e: e[0], reverse=True)[:40]
    return _page(request, "admin_user.html", admin, u=u, payments=payments, usage=usage_summary(db, u),
                 redemptions=redemptions, usages=usages, plans=load_plans(), timeline=timeline,
                 message=message, error=error, tab="users")


@router.post("/admin/users/{uid}/action")
def admin_user_action(request: Request, uid: int, db: Session = Depends(get_db),
                      admin: User = Depends(auth.require_writer), action: str = Form(...),
                      plan_id: str = Form("pro"), days: int = Form(30), notes: str = Form(""),
                      role: str = Form("user"), subject: str = Form(""), body: str = Form(""),
                      _csrf: None = Depends(csrf_protect)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Пользователь не найден.")
    msg = err = ""

    if action == "grant_plan":
        if not plan_exists(plan_id) or plan_id == "free":
            err = "Неверный тариф."
        else:
            billing._extend_plan(u, plan_id, max(1, int(days)))
            adminsvc.audit(db, admin, "user.grant_plan", f"user:{uid}", f"{plan_id} +{days}д")
            msg = f"Выдан тариф {plan_id} на {days} дн."
    elif action == "revoke_plan":
        u.plan_id, u.plan_until = "free", None
        adminsvc.audit(db, admin, "user.revoke_plan", f"user:{uid}")
        msg = "Тариф снят (free)."
    elif action == "reset_quota":
        rec = get_usage(db, u)
        rec.exports = 0
        adminsvc.audit(db, admin, "user.reset_quota", f"user:{uid}")
        msg = "Месячная квота сброшена."
    elif action == "verify_email":
        u.email_verified, u.verify_token = True, ""
        adminsvc.audit(db, admin, "user.verify_email", f"user:{uid}")
        msg = "Email отмечен подтверждённым."
    elif action == "toggle_block":
        if u.id == admin.id:
            err = "Нельзя заблокировать самого себя."
        else:
            u.is_active = not u.is_active
            adminsvc.audit(db, admin, "user.block" if not u.is_active else "user.unblock", f"user:{uid}")
            msg = "Аккаунт заблокирован." if not u.is_active else "Аккаунт разблокирован."
    elif action == "toggle_admin":
        if u.id == admin.id:
            err = "Нельзя снять админа с самого себя."
        else:
            u.is_admin = not u.is_admin
            adminsvc.audit(db, admin, "user.toggle_admin", f"user:{uid}", f"is_admin={u.is_admin}")
            msg = "Права администратора обновлены."
    elif action == "save_notes":
        u.notes = (notes or "")[:2000]
        adminsvc.audit(db, admin, "user.notes", f"user:{uid}")
        msg = "Заметки сохранены."
    elif action == "delete":
        if u.id == admin.id:
            err = "Нельзя удалить самого себя."
        else:
            adminsvc.audit(db, admin, "user.delete", f"user:{uid}", u.email)
            auth.delete_account(db, u)
            db.commit()
            return RedirectResponse(f"/admin/users?message={quote('Пользователь удалён.')}", 303)
    elif action == "reset_2fa":
        u.totp_enabled, u.totp_secret = False, ""
        adminsvc.audit(db, admin, "user.reset_2fa", f"user:{uid}")
        msg = "Двухфакторная аутентификация сброшена."
    elif action == "force_logout":
        u.session_epoch = (u.session_epoch or 0) + 1
        adminsvc.audit(db, admin, "user.force_logout", f"user:{uid}")
        msg = "Все сессии пользователя завершены."
    elif action == "send_email":
        from .email import send_email
        try:
            send_email(u.email, subject or "Сообщение от AssetForge", body or "")
            adminsvc.audit(db, admin, "user.email", f"user:{uid}", subject[:80])
            msg = "Письмо отправлено."
        except Exception:  # noqa: BLE001
            err = "Не удалось отправить письмо."
    elif action == "set_role":
        if not admin.is_superadmin:
            err = "Менять роли может только супер-админ."
        elif role not in ("user", "support", "admin", "superadmin"):
            err = "Неизвестная роль."
        elif u.id == admin.id:
            err = "Нельзя менять собственную роль."
        else:
            u.role = role
            u.is_admin = role in ("support", "admin", "superadmin")
            adminsvc.audit(db, admin, "user.set_role", f"user:{uid}", role)
            msg = f"Роль изменена на {role}."
    else:
        err = "Неизвестное действие."

    qs = f"?message={quote(msg)}" if msg else (f"?error={quote(err)}" if err else "")
    return RedirectResponse(f"/admin/users/{uid}{qs}", 303)


@router.post("/admin/users/{uid}/impersonate")
def admin_impersonate(request: Request, uid: int, db: Session = Depends(get_db),
                      admin: User = Depends(auth.require_writer), _csrf: None = Depends(csrf_protect)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Пользователь не найден.")
    request.session["imp_admin"] = admin.id
    auth.login_session(request, u)
    adminsvc.audit(db, admin, "user.impersonate", f"user:{uid}", u.email)
    return RedirectResponse("/app", 303)


@router.get("/admin/stop-impersonate")
def admin_stop_impersonate(request: Request):
    aid = request.session.pop("imp_admin", None)
    if aid:
        request.session["uid"] = aid
    return RedirectResponse("/admin", 303)


# --- промокоды --------------------------------------------------------------

@router.get("/admin/promos", response_class=HTMLResponse)
def admin_promos(request: Request, db: Session = Depends(get_db),
                 admin: User = Depends(auth.require_admin), message: str = ""):
    promos = db.scalars(select(PromoCode).order_by(PromoCode.created_at.desc())).all()
    return _page(request, "admin_promos.html", admin, promos=promos, plans=load_plans(),
                 message=message, tab="promos")


@router.post("/admin/promos/create")
def admin_create_promo(request: Request, db: Session = Depends(get_db),
                       admin: User = Depends(auth.require_writer),
                       code: str = Form(...), kind: str = Form(...), value: float = Form(0),
                       plan_id: str = Form("pro"), max_uses: int = Form(0), expires_days: int = Form(0),
                       _csrf: None = Depends(csrf_protect)):
    code = code.strip()
    err = ""
    if not code or kind not in ("percent", "free_days", "grant_plan"):
        err = "Проверьте код и тип."
    elif kind == "percent" and not (0 <= value <= 100):
        err = "Скидка должна быть 0–100%."
    elif kind in ("free_days", "grant_plan") and not (0 < value <= 3650):
        err = "Дней должно быть 1–3650."
    elif kind == "grant_plan" and (not plan_exists(plan_id) or plan_id == "free"):
        err = "Неверный тариф для выдачи."
    elif db.scalar(select(PromoCode).where(PromoCode.code == code)):
        err = "Такой код уже существует."
    if err:
        return RedirectResponse(f"/admin/promos?message={quote(err)}", 303)
    expires_at = (utcnow() + timedelta(days=int(expires_days))) if int(expires_days) > 0 else None
    db.add(PromoCode(code=code, kind=kind, value=value, plan_id=plan_id,
                     max_uses=max(0, int(max_uses)), expires_at=expires_at))
    adminsvc.audit(db, admin, "promo.create", code, f"{kind}={value}")
    return RedirectResponse(f"/admin/promos?message={quote('Промокод создан.')}", 303)


@router.post("/admin/promos/{pid}/toggle")
def admin_toggle_promo(request: Request, pid: int, db: Session = Depends(get_db),
                       admin: User = Depends(auth.require_writer), _csrf: None = Depends(csrf_protect)):
    p = db.get(PromoCode, pid)
    if p:
        p.active = not p.active
        adminsvc.audit(db, admin, "promo.toggle", p.code, f"active={p.active}")
    return RedirectResponse("/admin/promos", 303)


@router.post("/admin/promos/{pid}/delete")
def admin_delete_promo(request: Request, pid: int, db: Session = Depends(get_db),
                       admin: User = Depends(auth.require_writer), _csrf: None = Depends(csrf_protect)):
    p = db.get(PromoCode, pid)
    if p:
        adminsvc.audit(db, admin, "promo.delete", p.code)
        db.delete(p)
    return RedirectResponse("/admin/promos", 303)


# --- платежи ----------------------------------------------------------------

@router.get("/admin/payments", response_class=HTMLResponse)
def admin_payments(request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(auth.require_admin), status: str = "", page: int = 1):
    stmt = select(Payment)
    if status:
        stmt = stmt.where(Payment.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    pg = adminsvc.paginate(total, page, ADMIN_PER_PAGE)
    payments = db.scalars(stmt.order_by(Payment.created_at.desc())
                          .offset(pg["offset"]).limit(pg["per"])).all()
    return _page(request, "admin_payments.html", admin, payments=payments, pg=pg, status=status,
                 tab="payments")


@router.post("/admin/payment/{payment_id}/approve")
def admin_approve_payment(request: Request, payment_id: int, db: Session = Depends(get_db),
                          admin: User = Depends(auth.require_writer), _csrf: None = Depends(csrf_protect)):
    billing.mark_paid(db, payment_id)
    adminsvc.audit(db, admin, "payment.approve", f"payment:{payment_id}")
    adminsvc.notify(db, "Платёж подтверждён админом", f"payment:{payment_id}")
    return RedirectResponse("/admin/payments", 303)


@router.post("/admin/payment/{payment_id}/reject")
def admin_reject_payment(request: Request, payment_id: int, db: Session = Depends(get_db),
                         admin: User = Depends(auth.require_writer), _csrf: None = Depends(csrf_protect)):
    pay = db.get(Payment, payment_id)
    if pay and pay.status == "pending":
        pay.status = "failed"
        adminsvc.audit(db, admin, "payment.reject", f"payment:{payment_id}")
    return RedirectResponse("/admin/payments", 303)


# --- настройки --------------------------------------------------------------

@router.get("/admin/settings", response_class=HTMLResponse)
def admin_settings(request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(auth.require_admin), message: str = ""):
    return _page(request, "admin_settings.html", admin, cfg=adminsvc.all_settings(db),
                 message=message, tab="settings")


@router.post("/admin/settings")
def admin_save_settings(request: Request, db: Session = Depends(get_db),
                        admin: User = Depends(auth.require_writer),
                        registration_open: str = Form("0"), maintenance_mode: str = Form("0"),
                        announcement: str = Form(""), announcement_start: str = Form(""),
                        announcement_end: str = Form(""), telegram_token: str = Form(""),
                        telegram_chat: str = Form(""), notify_webhook: str = Form(""),
                        admin_ip_allowlist: str = Form(""), ip_blocklist: str = Form(""),
                        _csrf: None = Depends(csrf_protect)):
    adminsvc.set_setting(db, "registration_open", "1" if registration_open in ("1", "on", "true") else "0")
    adminsvc.set_setting(db, "maintenance_mode", "1" if maintenance_mode in ("1", "on", "true") else "0")
    adminsvc.set_setting(db, "telegram_token", telegram_token.strip())
    adminsvc.set_setting(db, "telegram_chat", telegram_chat.strip())
    adminsvc.set_setting(db, "notify_webhook", notify_webhook.strip())
    adminsvc.set_setting(db, "admin_ip_allowlist", admin_ip_allowlist.strip())
    adminsvc.set_setting(db, "ip_blocklist", ip_blocklist.strip())
    adminsvc.set_announcement(db, announcement, announcement_start, announcement_end)
    adminsvc.reload_ip_rules(db)
    adminsvc.audit(db, admin, "settings.update", "", f"reg={registration_open} maint={maintenance_mode}")
    return RedirectResponse(f"/admin/settings?message={quote('Настройки сохранены.')}", 303)


# --- управление тарифами ----------------------------------------------------

@router.get("/admin/plans", response_class=HTMLResponse)
def admin_plans(request: Request, db: Session = Depends(get_db),
                admin: User = Depends(auth.require_admin), message: str = ""):
    return _page(request, "admin_plans.html", admin, plans=load_plans(), message=message, tab="plans")


@router.post("/admin/plans")
async def admin_save_plans(request: Request, db: Session = Depends(get_db),
                           admin: User = Depends(auth.require_writer),
                           _csrf: None = Depends(csrf_protect)):
    from . import plans as plansmod
    form = await request.form()
    overrides: dict = {}
    for pid in load_plans():
        ov: dict = {}
        limits: dict = {}
        pr = form.get(f"{pid}_price_rub")
        if pr not in (None, ""):
            try: ov["price_rub"] = float(pr)
            except ValueError: pass
        for lk in ("exports_per_month", "max_dimension", "batch_max_files"):
            v = form.get(f"{pid}_{lk}")
            if v not in (None, ""):
                try: limits[lk] = int(float(v))
                except ValueError: pass
        limits["ai_background"] = form.get(f"{pid}_ai_background") in ("1", "on", "true")
        fmts = form.get(f"{pid}_formats")
        if fmts:
            parsed = [x.strip().lower() for x in fmts.split(",") if x.strip()]
            if parsed:
                limits["formats"] = parsed
        if limits:
            ov["limits"] = limits
        if ov:
            overrides[pid] = ov
    adminsvc.save_plan_overrides(db, overrides)
    plansmod.apply_overrides(overrides)
    adminsvc.audit(db, admin, "plans.update", "", str(list(overrides.keys())))
    return RedirectResponse(f"/admin/plans?message={quote('Тарифы обновлены.')}", 303)


# --- вебхуки (лог) ----------------------------------------------------------

@router.get("/admin/webhooks", response_class=HTMLResponse)
def admin_webhooks(request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(auth.require_admin), page: int = 1):
    total = db.scalar(select(func.count(WebhookEvent.id))) or 0
    pg = adminsvc.paginate(total, page, 50)
    rows = db.scalars(select(WebhookEvent).order_by(WebhookEvent.created_at.desc())
                      .offset(pg["offset"]).limit(pg["per"])).all()
    return _page(request, "admin_webhooks.html", admin, rows=rows, pg=pg, tab="webhooks")


# --- журнал действий --------------------------------------------------------

@router.get("/admin/audit", response_class=HTMLResponse)
def admin_audit_log(request: Request, db: Session = Depends(get_db),
                    admin: User = Depends(auth.require_admin), page: int = 1):
    total = db.scalar(select(func.count(AuditLog.id))) or 0
    pg = adminsvc.paginate(total, page, 50)
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc())
                      .offset(pg["offset"]).limit(pg["per"])).all()
    return _page(request, "admin_audit.html", admin, rows=rows, pg=pg, tab="audit")


# --- здоровье системы / логи / входы ---------------------------------------

@router.get("/admin/health", response_class=HTMLResponse)
def admin_health(request: Request, db: Session = Depends(get_db),
                 admin: User = Depends(auth.require_admin)):
    from ..kvstore import backend
    checks = {}
    try:
        db.execute(select(func.count(User.id))).scalar()
        checks["База данных"] = ("ok", settings.db_url.split("://", 1)[0])
    except Exception as exc:  # noqa: BLE001
        checks["База данных"] = ("fail", str(exc)[:80])
    try:
        b = backend()
        checks["KV-хранилище"] = ("ok", b.name)
    except Exception as exc:  # noqa: BLE001
        checks["KV-хранилище"] = ("fail", str(exc)[:80])
    for name, ok in provider_status().items():
        checks[f"Платежи: {name}"] = ("ok", "подключён") if ok else ("warn", "заглушка")
    counts = {
        "Пользователей": db.scalar(select(func.count(User.id))) or 0,
        "Платежей": db.scalar(select(func.count(Payment.id))) or 0,
        "Входов (журнал)": db.scalar(select(func.count(LoginEvent.id))) or 0,
    }
    return _page(request, "admin_health.html", admin, checks=checks, counts=counts, tab="health")


@router.get("/admin/logs", response_class=HTMLResponse)
def admin_logs(request: Request, admin: User = Depends(auth.require_admin), level: str = ""):
    from ..logging_setup import recent_logs
    return _page(request, "admin_logs.html", admin, rows=recent_logs(200, level or None),
                 level=level, tab="logs")


@router.get("/admin/logins", response_class=HTMLResponse)
def admin_logins(request: Request, db: Session = Depends(get_db),
                 admin: User = Depends(auth.require_admin), page: int = 1):
    total = db.scalar(select(func.count(LoginEvent.id))) or 0
    pg = adminsvc.paginate(total, page, 50)
    rows = db.scalars(select(LoginEvent).order_by(LoginEvent.created_at.desc())
                      .offset(pg["offset"]).limit(pg["per"])).all()
    return _page(request, "admin_logins.html", admin, rows=rows, pg=pg, tab="logins")


# --- релизы десктопа --------------------------------------------------------

@router.get("/admin/releases", response_class=HTMLResponse)
def admin_releases(request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(auth.require_admin), message: str = ""):
    releases = db.scalars(select(DesktopRelease).order_by(DesktopRelease.created_at.desc())).all()
    versions = db.scalars(select(VersionStat).order_by(VersionStat.count.desc())).all()
    return _page(request, "admin_releases.html", admin, releases=releases, versions=versions,
                 message=message, tab="releases")


@router.post("/admin/releases/upload")
async def admin_release_upload(request: Request, db: Session = Depends(get_db),
                               admin: User = Depends(auth.require_writer)):
    from .desktop_dist import release_dir
    form = await request.form()
    if not csrf_verify(request, form.get("csrf_token", "")):
        raise HTTPException(403, "Сессия устарела, обновите страницу.")
    version = (form.get("version") or "").strip()[:40]
    notes = (form.get("notes") or "").strip()[:2000]
    upload = form.get("file")
    if not version or upload is None or not getattr(upload, "filename", ""):
        return RedirectResponse(f"/admin/releases?message={quote('Укажите версию и файл.')}", 303)
    fname = f"AssetForge-{version}.exe"
    dest = release_dir() / fname
    data = await upload.read()
    dest.write_bytes(data)
    db.execute(update(DesktopRelease).values(is_current=False))
    db.add(DesktopRelease(version=version, notes=notes, filename=fname,
                          size=len(data), is_current=True))
    adminsvc.audit(db, admin, "release.upload", version, f"{len(data)} bytes")
    return RedirectResponse(f"/admin/releases?message={quote('Релиз загружен и сделан текущим.')}", 303)


@router.post("/admin/releases/{rid}/current")
def admin_release_current(request: Request, rid: int, db: Session = Depends(get_db),
                          admin: User = Depends(auth.require_writer), _csrf: None = Depends(csrf_protect)):
    rel = db.get(DesktopRelease, rid)
    if rel:
        db.execute(update(DesktopRelease).values(is_current=False))
        rel.is_current = True
        adminsvc.audit(db, admin, "release.set_current", rel.version)
    return RedirectResponse("/admin/releases", 303)


@router.post("/admin/releases/{rid}/delete")
def admin_release_delete(request: Request, rid: int, db: Session = Depends(get_db),
                         admin: User = Depends(auth.require_writer), _csrf: None = Depends(csrf_protect)):
    from .desktop_dist import release_dir
    rel = db.get(DesktopRelease, rid)
    if rel:
        try:
            (release_dir() / rel.filename).unlink(missing_ok=True)
        except OSError:
            pass
        adminsvc.audit(db, admin, "release.delete", rel.version)
        db.delete(rel)
    return RedirectResponse("/admin/releases", 303)


# --- A/B фича-флаги ----------------------------------------------------------

@router.get("/admin/flags", response_class=HTMLResponse)
def admin_flags(request: Request, db: Session = Depends(get_db),
                admin: User = Depends(auth.require_admin), message: str = ""):
    return _page(request, "admin_flags.html", admin, flags=flags.all_flags(db),
                 message=message, tab="flags")


@router.post("/admin/flags/save")
def admin_flag_save(request: Request, db: Session = Depends(get_db),
                    admin: User = Depends(auth.require_writer), name: str = Form(...),
                    rollout: int = Form(0), enabled: str = Form("0"), description: str = Form(""),
                    _csrf: None = Depends(csrf_protect)):
    name = name.strip()[:60]
    if not name:
        return RedirectResponse("/admin/flags", 303)
    f = db.get(FeatureFlag, name) or FeatureFlag(name=name)
    f.rollout = max(0, min(100, int(rollout)))
    f.enabled = enabled in ("1", "on", "true")
    f.description = (description or "")[:255]
    db.add(f)
    adminsvc.audit(db, admin, "flag.save", name, f"rollout={f.rollout} on={f.enabled}")
    return RedirectResponse(f"/admin/flags?message={quote('Флаг сохранён.')}", 303)


@router.post("/admin/flags/{name}/delete")
def admin_flag_delete(request: Request, name: str, db: Session = Depends(get_db),
                      admin: User = Depends(auth.require_writer), _csrf: None = Depends(csrf_protect)):
    f = db.get(FeatureFlag, name)
    if f:
        db.delete(f)
        adminsvc.audit(db, admin, "flag.delete", name)
    return RedirectResponse("/admin/flags", 303)


# --- когорты ----------------------------------------------------------------

@router.get("/admin/cohorts", response_class=HTMLResponse)
def admin_cohorts(request: Request, db: Session = Depends(get_db),
                  admin: User = Depends(auth.require_admin)):
    return _page(request, "admin_cohorts.html", admin, rows=adminsvc.cohorts(db, 12), tab="cohorts")


# --- экспорт CSV ------------------------------------------------------------

@router.get("/admin/export/users.csv")
def admin_export_users(db: Session = Depends(get_db), admin: User = Depends(auth.require_admin)):
    def gen():
        buf = _io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "email", "name", "plan", "plan_until", "is_admin", "is_active", "created_at"])
        yield buf.getvalue(); buf.seek(0); buf.truncate(0)
        for u in db.scalars(select(User).order_by(User.id)).all():
            w.writerow([u.id, u.email, u.name, u.effective_plan(),
                        u.plan_until.isoformat() if u.plan_until else "",
                        int(u.is_admin), int(u.is_active), u.created_at.isoformat()])
            yield buf.getvalue(); buf.seek(0); buf.truncate(0)
    return StreamingResponse(gen(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="users.csv"'})


@router.get("/admin/export/payments.csv")
def admin_export_payments(db: Session = Depends(get_db), admin: User = Depends(auth.require_admin)):
    def gen():
        buf = _io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "user_id", "plan", "amount", "currency", "status", "provider",
                    "promo", "created_at", "paid_at"])
        yield buf.getvalue(); buf.seek(0); buf.truncate(0)
        for p in db.scalars(select(Payment).order_by(Payment.id)).all():
            w.writerow([p.id, p.user_id, p.plan_id, p.amount, p.currency, p.status, p.provider,
                        p.promo_code, p.created_at.isoformat(),
                        p.paid_at.isoformat() if p.paid_at else ""])
            yield buf.getvalue(); buf.seek(0); buf.truncate(0)
    return StreamingResponse(gen(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="payments.csv"'})
