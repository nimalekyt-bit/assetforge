"""Облачное SaaS-приложение AssetForge.

Лендинг + аккаунты + тарифы + оплата + личный кабинет + админка, а сам инструмент
(тот же движок) смонтирован под /app и /api/* с проверкой авторизации и лимитов тарифа.

Запуск:  uvicorn assetforge.saas.app:app --port 8000
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from ..resources import web_dir
from ..server import app as toolapp          # переиспользуем готовые ручки инструмента
from ..logging_setup import get_logger
from . import auth, quota
from .config import settings
from .db import get_db, init_db
from .quota import enforce_export, usage_summary
from . import adminsvc
from .routes import router as pages_router
from .desktop_dist import router as desktop_router
from .desktop_auth import router as desktop_auth_router

SAAS_STATIC = Path(__file__).resolve().parent / "static"
log = get_logger("saas")

# проверка безопасности конфигурации (в проде поднимет исключение, в dev — предупреждения)
for _warn in settings.validate_for_production():
    log.warning("[SECURITY] %s", _warn)

app = FastAPI(title="AssetForge SaaS", version="1.0.0")
# session-cookie: строгий SameSite (защита от CSRF) + умеренный срок жизни
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key,
                   max_age=60 * 60 * 24 * 7, same_site="strict", https_only=settings.cookie_secure)


@app.middleware("http")
async def _ip_guard(request: Request, call_next):
    """IP-фильтр: глобальный блок-лист + allowlist для /admin (анти-абьюз и доступ)."""
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
    try:
        bl = adminsvc.current_ip_blocklist()
        if bl and adminsvc.ip_matches(ip, bl):
            return JSONResponse({"detail": "Доступ запрещён."}, status_code=403)
        if request.url.path.startswith("/admin"):
            al = adminsvc.current_admin_allowlist()
            if al and not adminsvc.ip_matches(ip, al):
                return JSONResponse({"detail": "Админка недоступна с этого IP."}, status_code=403)
    except Exception:  # noqa: BLE001 — фильтр не должен ронять запросы
        pass
    return await call_next(request)


init_db()  # создаём таблицы при импорте (idempotent)

# подтянуть из БД переопределения тарифов и анонс (graceful — не падаем, если БД ещё пуста)
try:
    from .db import session_scope
    from . import adminsvc as _adminsvc
    with session_scope() as _s:
        _adminsvc.bootstrap(_s)
except Exception as _e:  # noqa: BLE001
    log.warning("bootstrap настроек не выполнен: %s", _e)

app.include_router(pages_router)
app.include_router(desktop_router)
app.include_router(desktop_auth_router)
from .api_v1 import router as api_v1_router
app.include_router(api_v1_router)
app.mount("/saas-static", StaticFiles(directory=str(SAAS_STATIC)), name="saas-static")
app.mount("/static", StaticFiles(directory=str(web_dir())), name="static")


# --- обработка ошибок: красивые HTML-страницы для сайта, JSON для /api --------

def _wants_json(request: Request) -> bool:
    p = request.url.path
    return p.startswith("/api/") or p.startswith("/billing/webhook")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if _wants_json(request):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    # анонимам на защищённых страницах — на вход, а не голый 401
    if exc.status_code == 401:
        return RedirectResponse(f"/login?next={request.url.path}", 303)
    from .routes import TEMPLATES
    return TEMPLATES.TemplateResponse(
        request, "error.html",
        {"user": None, "code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Необработанная ошибка на %s %s", request.method, request.url.path)
    if _wants_json(request):
        return JSONResponse({"detail": "Внутренняя ошибка сервера."}, status_code=500)
    from .routes import TEMPLATES
    return TEMPLATES.TemplateResponse(
        request, "error.html",
        {"user": None, "code": 500, "detail": "Что-то пошло не так. Мы уже разбираемся."},
        status_code=500,
    )


# --- страница инструмента (под авторизацией) --------------------------------

@app.get("/app", response_class=HTMLResponse)
def tool_page(request: Request, db: Session = Depends(get_db), user=Depends(auth.current_user)):
    if not user:
        return RedirectResponse("/login?next=/app", 303)
    from . import adminsvc
    if adminsvc.get_bool(db, "maintenance_mode") and not user.is_admin:
        from .routes import TEMPLATES
        return TEMPLATES.TemplateResponse(request, "info_message.html",
            {"user": user, "title": "Технические работы",
             "ok": False, "message": "Идут технические работы. Инструмент скоро снова заработает."},
            status_code=503)
    html = (web_dir() / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/me")
def api_me(db: Session = Depends(get_db), user=Depends(auth.require_user)):
    from .plans import plan_limits
    from . import flags as _flags
    plan = user.effective_plan()
    return {
        "email": user.email,
        "name": user.name,
        "plan": plan,
        "limits": plan_limits(plan),
        "is_admin": user.is_admin,
        "flags": _flags.active_flags(db, user),
        "usage": usage_summary(db, user),
    }


# --- инструмент: те же ручки, но под require_user (+ квоты на экспорт) -------

@app.get("/api/presets")
def presets(user=Depends(auth.require_user)):
    return toolapp.api_presets()


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), user=Depends(auth.require_user)):
    return await toolapp.upload_impl(file, owner=f"u{user.id}")


@app.post("/api/analyze")
async def analyze(payload: dict = None, user=Depends(auth.require_user)):
    return await toolapp.api_analyze(payload)


@app.post("/api/preview")
async def preview(payload: dict = None, user=Depends(auth.require_user)):
    return await toolapp.api_preview(payload)


@app.post("/api/export")
async def export(payload: dict = None, db: Session = Depends(get_db),
                 user=Depends(auth.require_user)):
    payload = payload or {}
    cfg = toolapp._cfg_from(payload)
    sess = toolapp.STORE.get(payload.get("session_id", ""))
    if not sess:
        raise HTTPException(404, "Сессия не найдена.")
    objects = sess.objects(cfg)
    which = payload.get("object_index", "all")
    count = max(1, len(objects) if which in ("all", None) else 1)
    ai = cfg.background.mode == "ai"
    # 1) фичи/лимиты тарифа (понятное сообщение об апгрейде)
    enforce_export(db, user, sizes=cfg.export.sizes, formats=cfg.export.formats,
                   batch_files=1, ai=ai, count=count)
    # 2) атомарно резервируем квоту (защита от гонки параллельных экспортов)
    period = quota.current_period()
    if not quota.try_consume(db, user, count, period):
        raise HTTPException(402, "Исчерпан лимит экспортов в этом месяце. Перейдите на Pro: /pricing")
    try:
        return await toolapp.api_export(payload)
    except Exception:
        quota.refund(db, user, count, period)       # нарезка не удалась — возвращаем квоту
        raise


@app.post("/api/batch")
async def batch(files: list[UploadFile] = File(...), preset_name: str = Form("icon-set"),
                config: str = Form("{}"), db: Session = Depends(get_db),
                user=Depends(auth.require_user)):
    overrides = json.loads(config or "{}")
    cfg = toolapp._cfg_from({"preset": preset_name, "config": overrides})
    ai = cfg.background.mode == "ai"
    enforce_export(db, user, sizes=cfg.export.sizes, formats=cfg.export.formats,
                   batch_files=len(files), ai=ai, count=len(files))
    period = quota.current_period()
    if not quota.try_consume(db, user, len(files), period):
        raise HTTPException(402, "Исчерпан лимит экспортов в этом месяце. Перейдите на Pro: /pricing")
    try:
        return await toolapp.api_batch(files, preset_name, config)
    except Exception:
        quota.refund(db, user, len(files), period)
        raise
