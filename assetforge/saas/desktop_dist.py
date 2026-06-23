"""Раздача desktop-дистрибутива: страница скачивания, манифест обновлений и сам .exe.

Текущий релиз управляется из админки (модель DesktopRelease, каталог релизов).
Если релизов в БД нет — фолбэк на собранный dist/AssetForge.exe и __version__.

  GET /desktop                      — брендированная страница скачивания
  GET /desktop/latest.json          — манифест версии (для авто-обновления + учёт версий)
  GET /desktop/AssetForge-Setup.exe — текущий установщик/приложение
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__
from . import adminsvc, auth
from .config import settings
from .db import get_db
from .models import DesktopRelease
from .routes import TEMPLATES

router = APIRouter()

SETUP_NAME = "AssetForge-Setup.exe"


def release_dir() -> Path:
    d = os.environ.get("ASSETFORGE_RELEASE_DIR", "").strip()
    base = Path(d) if d else Path(__file__).resolve().parents[2] / "desktop_releases"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _fallback_exe() -> Path:
    env = os.environ.get("ASSETFORGE_DESKTOP_EXE", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "dist" / "AssetForge.exe"


def current_release(db: Session) -> DesktopRelease | None:
    return db.scalar(select(DesktopRelease).where(DesktopRelease.is_current.is_(True)))


def resolved(db: Session) -> tuple[str, Path, int]:
    """(версия, путь к файлу, размер) — из текущего релиза или фолбэк на dist."""
    rel = current_release(db)
    if rel:
        p = release_dir() / rel.filename
        if p.exists():
            return rel.version, p, p.stat().st_size
    p = _fallback_exe()
    size = p.stat().st_size if p.exists() else 0
    return __version__, p, size


def _setup_url() -> str:
    return f"{settings.base_url.rstrip('/')}/desktop/{SETUP_NAME}"


@router.get("/desktop", response_class=HTMLResponse)
def desktop_page(request: Request, db: Session = Depends(get_db), user=Depends(auth.current_user)):
    version, path, size = resolved(db)
    rel = current_release(db)
    return TEMPLATES.TemplateResponse(request, "desktop.html", {
        "user": user, "version": version, "available": path.exists(),
        "size_mb": round(size / 1048576, 1) if size else 0,
        "notes": rel.notes if rel else "",
    })


@router.get("/desktop/latest.json")
def latest_manifest(request: Request, db: Session = Depends(get_db)):
    frm = request.query_params.get("from", "")
    if frm:
        adminsvc.record_version(db, frm)
    version, path, size = resolved(db)
    rel = current_release(db)
    return JSONResponse({
        "version": version,
        "url": _setup_url(),
        "notes": (rel.notes if rel else f"AssetForge {version}"),
        "size": size,
    })


@router.get("/desktop/" + SETUP_NAME)
def download_setup(db: Session = Depends(get_db)):
    _v, path, _s = resolved(db)
    if not path.exists():
        raise HTTPException(404, "Сборка ещё не выложена.")
    return FileResponse(str(path), media_type="application/octet-stream", filename=SETUP_NAME)
