"""Desktop-вариант сервера AssetForge (фримиум, Вариант C).

Переиспользует ручки инструмента из server.app, но:
  • экспорт/batch проходят проверку прав (гость vs тариф) — entitlement.enforce;
  • добавлены /api/desktop/{status,login,logout} для входа в облачный аккаунт.

Облако (квоты/оплата) не трогаем — desktop ходит туда только за логином и тарифом.
"""
from __future__ import annotations

import json

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import cloud
from ..resources import web_dir
from . import app as toolapp
from . import entitlement

WEB_DIR = web_dir()

app = FastAPI(title="AssetForge Desktop", version="0.1.0")


# --- passthrough: те же ручки инструмента (без изменений) -------------------

@app.get("/api/presets")
def presets() -> JSONResponse:
    return toolapp.api_presets()


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> JSONResponse:
    return await toolapp.api_upload(file)


@app.post("/api/analyze")
async def analyze(payload: dict = None) -> JSONResponse:
    return await toolapp.api_analyze(payload)


@app.post("/api/preview")
async def preview(payload: dict = None) -> JSONResponse:
    return await toolapp.api_preview(payload)


# --- экспорт/batch: с проверкой прав ----------------------------------------

@app.post("/api/export")
async def export(payload: dict = None) -> Response:
    payload = payload or {}
    cfg = toolapp._cfg_from(payload)
    entitlement.enforce(cfg, batch_files=1)        # гость/тариф: размеры, форматы, AI
    return await toolapp.api_export(payload)


@app.post("/api/batch")
async def batch(files: list[UploadFile] = File(...), preset_name: str = Form("icon-set"),
                config: str = Form("{}")) -> Response:
    overrides = json.loads(config or "{}")
    cfg = toolapp._cfg_from({"preset": preset_name, "config": overrides})
    entitlement.enforce(cfg, batch_files=len(files))
    return await toolapp.api_batch(files, preset_name, config)


# --- desktop-аккаунт --------------------------------------------------------

@app.get("/api/desktop/status")
def desktop_status() -> JSONResponse:
    return JSONResponse(entitlement.status())


@app.post("/api/desktop/login")
def desktop_login(payload: dict = None) -> JSONResponse:
    payload = payload or {}
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    if not email or not password:
        return JSONResponse({"ok": False, "error": "Введите email и пароль."}, status_code=200)

    resp = cloud.post_json("/api/desktop/auth", {"email": email, "password": password})
    if resp is None:
        return JSONResponse({"ok": False, "error": "Нет связи с сервером AssetForge. Проверьте интернет."},
                            status_code=200)
    if not resp.get("ok"):
        return JSONResponse({"ok": False, "error": resp.get("error") or "Не удалось войти."},
                            status_code=200)

    entitlement.set_logged_in(resp["token"], resp.get("email", email), resp.get("name"),
                              resp.get("plan", "free"), resp.get("limits") or {})
    return JSONResponse({"ok": True, **entitlement.status()})


@app.post("/api/desktop/logout")
def desktop_logout() -> JSONResponse:
    entitlement.clear()
    return JSONResponse({"ok": True, **entitlement.status()})


# --- статика / SPA (как в server.app) ---------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return toolapp.index()


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
