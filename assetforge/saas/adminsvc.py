"""Сервисы админки: аудит действий, рантайм-настройки, метрики дашборда."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AppSetting, AuditLog, Payment, UsageRecord, User, utcnow
from .models import _aware as _aware
from .plans import display_price, get_plan
from .quota import current_period


# --- аудит -----------------------------------------------------------------

def audit(db: Session, admin: User | None, action: str, target: str = "", detail: str = "") -> None:
    db.add(AuditLog(
        admin_id=getattr(admin, "id", None),
        admin_email=getattr(admin, "email", "") or "",
        action=action, target=target, detail=detail[:500],
    ))
    db.flush()


# --- рантайм-настройки (AppSetting) ----------------------------------------

_DEFAULTS = {
    "registration_open": "1",
    "maintenance_mode": "0",
    "telegram_token": "",
    "telegram_chat": "",
    "notify_webhook": "",
    "announcement_start": "",
    "announcement_end": "",
    "admin_ip_allowlist": "",
    "ip_blocklist": "",
}


def get_setting(db: Session, key: str, default: str | None = None) -> str:
    row = db.get(AppSetting, key)
    if row is not None:
        return row.value
    return _DEFAULTS.get(key, default if default is not None else "")


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=str(value)))
    else:
        row.value = str(value)
    db.flush()


def get_bool(db: Session, key: str) -> bool:
    return str(get_setting(db, key)).lower() in ("1", "true", "yes", "on")


def all_settings(db: Session) -> dict[str, str]:
    rows = {s.key: s.value for s in db.scalars(select(AppSetting)).all()}
    return {**_DEFAULTS, **rows}


# --- переопределения тарифов (редактирование из админки) -------------------

def load_plan_overrides(db: Session) -> dict:
    import json
    raw = get_setting(db, "plan_overrides", "")
    try:
        return json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        return {}


def save_plan_overrides(db: Session, overrides: dict) -> None:
    import json
    set_setting(db, "plan_overrides", json.dumps(overrides))


# --- анонс (баннер на сайте) c расписанием ---------------------------------

_announcement: str = ""
_ann_start = None
_ann_end = None
_admin_allowlist: list[str] = []
_ip_blocklist: list[str] = []


def _parse_dt(s: str):
    from datetime import datetime, timezone
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def current_announcement() -> str:
    """Текст анонса, если он задан и попадает в окно расписания (пустые границы = всегда)."""
    if not _announcement:
        return ""
    now = utcnow()
    if _ann_start and now < _ann_start:
        return ""
    if _ann_end and now > _ann_end:
        return ""
    return _announcement


def load_announcement(db: Session) -> None:
    global _announcement, _ann_start, _ann_end
    _announcement = get_setting(db, "announcement", "")
    _ann_start = _parse_dt(get_setting(db, "announcement_start", ""))
    _ann_end = _parse_dt(get_setting(db, "announcement_end", ""))


def set_announcement(db: Session, text: str, start: str = "", end: str = "") -> None:
    global _announcement, _ann_start, _ann_end
    _announcement = (text or "").strip()[:500]
    set_setting(db, "announcement", _announcement)
    set_setting(db, "announcement_start", (start or "").strip())
    set_setting(db, "announcement_end", (end or "").strip())
    _ann_start, _ann_end = _parse_dt(start), _parse_dt(end)


# --- IP allowlist (админка) / blocklist (весь сайт) ------------------------

def _ip_list(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").replace("\n", ",").split(",") if x.strip()]


def current_admin_allowlist() -> list[str]:
    return _admin_allowlist


def current_ip_blocklist() -> list[str]:
    return _ip_blocklist


def reload_ip_rules(db: Session) -> None:
    global _admin_allowlist, _ip_blocklist
    _admin_allowlist = _ip_list(get_setting(db, "admin_ip_allowlist", ""))
    _ip_blocklist = _ip_list(get_setting(db, "ip_blocklist", ""))


def ip_matches(ip: str, rules: list[str]) -> bool:
    """Совпадает ли IP с каким-либо правилом (точный адрес или CIDR)."""
    if not ip or not rules:
        return False
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for rule in rules:
        try:
            if "/" in rule:
                if addr in ipaddress.ip_network(rule, strict=False):
                    return True
            elif ip == rule:
                return True
        except ValueError:
            continue
    return False


def record_version(db: Session, version: str) -> None:
    """Учесть пинг версии desktop-приложения (для статистики версий)."""
    from .models import VersionStat
    version = (version or "").strip()[:40]
    if not version:
        return
    row = db.get(VersionStat, version)
    if row is None:
        db.add(VersionStat(version=version, count=1, last_seen=utcnow()))
    else:
        row.count += 1
        row.last_seen = utcnow()


def cohorts(db: Session, months: int = 6) -> list[dict]:
    """Когорты по месяцу регистрации: всего и сколько сейчас платят."""
    now = utcnow()
    users = db.scalars(select(User).where(User.created_at > now - timedelta(days=months * 31 + 5))).all()
    buckets: dict[str, dict] = {}
    for u in users:
        key = _aware(u.created_at).strftime("%Y-%m")
        b = buckets.setdefault(key, {"month": key, "signups": 0, "paying": 0})
        b["signups"] += 1
        if u.plan_id != "free" and u.plan_until and _aware(u.plan_until) > now:
            b["paying"] += 1
    out = []
    for b in sorted(buckets.values(), key=lambda x: x["month"], reverse=True):
        b["conversion"] = round(b["paying"] / b["signups"] * 100, 1) if b["signups"] else 0.0
        out.append(b)
    return out


def bootstrap(db: Session) -> None:
    """Загрузить из БД переопределения тарифов, анонс и IP-правила при старте."""
    from . import plans
    plans.apply_overrides(load_plan_overrides(db))
    load_announcement(db)
    reload_ip_rules(db)


# --- метрики дашборда ------------------------------------------------------

def dashboard_metrics(db: Session) -> dict:
    now = utcnow()
    total_users = db.scalar(select(func.count(User.id))) or 0

    # активные платные = plan_id != free И plan_until в будущем
    paid_rows = db.execute(
        select(User.plan_id, func.count(User.id))
        .where(User.plan_id != "free", User.plan_until.is_not(None), User.plan_until > now)
        .group_by(User.plan_id)
    ).all()
    paid_users = sum(c for _, c in paid_rows)
    # MRR — сумма месячных цен активных платных по их тарифам (в валюте отображения)
    mrr = 0.0
    for plan_id, count in paid_rows:
        mrr += display_price(get_plan(plan_id)) * count

    revenue_total = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(Payment.status == "paid")) or 0.0
    revenue_30d = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0.0))
        .where(Payment.status == "paid", Payment.paid_at.is_not(None),
               Payment.paid_at > now - timedelta(days=30))) or 0.0

    def signups_since(days: int) -> int:
        return db.scalar(select(func.count(User.id))
                         .where(User.created_at > now - timedelta(days=days))) or 0

    pending = db.scalar(select(func.count(Payment.id)).where(Payment.status == "pending")) or 0
    exports_period = db.scalar(
        select(func.coalesce(func.sum(UsageRecord.exports), 0))
        .where(UsageRecord.period == current_period())) or 0

    conv = (paid_users / total_users * 100) if total_users else 0.0

    return {
        "total_users": total_users,
        "paid_users": paid_users,
        "free_users": total_users - paid_users,
        "mrr": round(mrr, 2),
        "arr": round(mrr * 12, 2),
        "arpu": round(mrr / paid_users, 2) if paid_users else 0.0,
        "revenue_total": round(revenue_total, 2),
        "revenue_30d": round(revenue_30d, 2),
        "signups_24h": signups_since(1),
        "signups_7d": signups_since(7),
        "signups_30d": signups_since(30),
        "conversion": round(conv, 1),
        "pending_payments": pending,
        "exports_period": exports_period,
        "period": current_period(),
        "signups_series": _signups_series(db, 14),
        "revenue_series": _revenue_series(db, 12),
    }


def _revenue_series(db: Session, months: int) -> list[dict]:
    """Выручка по месяцам за последние `months` (агрегируем в Python — кросс-диалектно)."""
    now = utcnow()
    rows = db.execute(
        select(Payment.amount, Payment.paid_at)
        .where(Payment.status == "paid", Payment.paid_at.is_not(None),
               Payment.paid_at > now - timedelta(days=months * 31 + 5))
    ).all()
    buckets: dict[str, float] = {}
    for amt, paid_at in rows:
        key = _aware(paid_at).strftime("%Y-%m")
        buckets[key] = buckets.get(key, 0.0) + float(amt or 0)
    y, m = now.year, now.month
    keys = []
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    keys.reverse()
    return [{"m": k[2:], "v": round(buckets.get(k, 0.0), 2)} for k in keys]


def _signups_series(db: Session, days: int) -> list[dict]:
    """Регистрации по дням за последние `days` дней (для мини-графика)."""
    now = utcnow()
    rows = db.execute(
        select(func.date(User.created_at), func.count(User.id))
        .where(User.created_at > now - timedelta(days=days))
        .group_by(func.date(User.created_at))
    ).all()
    by_day = {str(d): c for d, c in rows}
    out = []
    for i in range(days - 1, -1, -1):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        out.append({"day": day[5:], "count": by_day.get(day, 0)})
    return out


# --- пагинация -------------------------------------------------------------

def paginate(total: int, page: int, per: int) -> dict:
    page = max(1, page)
    pages = max(1, (total + per - 1) // per)
    page = min(page, pages)
    return {"page": page, "pages": pages, "per": per, "total": total,
            "offset": (page - 1) * per, "has_prev": page > 1, "has_next": page < pages}


# --- аналитика для графиков (Chart.js) -------------------------------------

def analytics(db: Session, days: int = 30) -> dict:
    """Серии данных для графиков дашборда за выбранный период."""
    now = utcnow()
    # распределение по тарифам
    paid_rows = db.execute(
        select(User.plan_id, func.count(User.id))
        .where(User.plan_id != "free", User.plan_until.is_not(None), User.plan_until > now)
        .group_by(User.plan_id)
    ).all()
    total = db.scalar(select(func.count(User.id))) or 0
    paid = sum(c for _, c in paid_rows)
    plan_distribution = [{"plan": "free", "count": total - paid}]
    plan_distribution += [{"plan": pid, "count": c} for pid, c in paid_rows]
    # статусы платежей
    pay_rows = db.execute(select(Payment.status, func.count(Payment.id)).group_by(Payment.status)).all()
    payment_status = [{"status": s, "count": c} for s, c in pay_rows]
    return {
        "days": days,
        "signups": _signups_series(db, days),
        "revenue": _revenue_series(db, 12),
        "plan_distribution": plan_distribution,
        "payment_status": payment_status,
    }


# --- журнал входов ----------------------------------------------------------

def record_login(db: Session, user, email: str, ip: str, success: bool, kind: str = "login") -> None:
    from .models import LoginEvent
    db.add(LoginEvent(user_id=getattr(user, "id", None), email=(email or "")[:255],
                      ip=(ip or "")[:64], success=success, kind=kind))


# --- внешние уведомления (Telegram / generic webhook) -----------------------

def notify(db: Session, title: str, text: str) -> None:
    """Отправить уведомление в Telegram и/или generic webhook (fire-and-forget)."""
    token = get_setting(db, "telegram_token", "")
    chat = get_setting(db, "telegram_chat", "")
    hook = get_setting(db, "notify_webhook", "")
    message = f"{title}\n{text}" if text else title
    targets: list[tuple[str, bytes]] = []
    if token and chat:
        import json
        from urllib.parse import quote as _q
        targets.append((f"https://api.telegram.org/bot{token}/sendMessage"
                        f"?chat_id={_q(chat)}&text={_q(message)}", b""))
    if hook:
        import json
        targets.append((hook, json.dumps({"title": title, "text": text}).encode("utf-8")))
    if not targets:
        return
    import threading

    def _send():
        import urllib.request
        for url, body in targets:
            try:
                req = urllib.request.Request(url, data=body or None,
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5).read()
            except Exception as exc:  # noqa: BLE001
                log.warning("notify не доставлен: %s", exc)
    threading.Thread(target=_send, daemon=True).start()
