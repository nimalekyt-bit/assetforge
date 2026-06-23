"""Публичный REST API (v1) для интеграций — аутентификация по API-ключу.

  GET  /api/v1/me        — тариф и остаток квоты
  POST /api/v1/cutout    — обработать изображение → ZIP (1 вызов = 1 экспорт квоты)

Авторизация: заголовок `Authorization: Bearer af_...` или `X-API-Key: af_...`.
Лимиты тарифа (размер/форматы/AI) и месячная квота — те же, что в вебе.
"""
from __future__ import annotations

import io
import json
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from ..core import pipeline
from ..server import app as toolapp
from . import apikeys, quota
from .db import get_db
from .models import User
from .plans import plan_limits

router = APIRouter(prefix="/api/v1")


def get_api_user(request: Request, db: Session = Depends(get_db)) -> User:
    h = request.headers.get("authorization", "")
    raw = h[7:].strip() if h.lower().startswith("bearer ") else request.headers.get("x-api-key", "")
    user = apikeys.verify_key(db, raw)
    if not user:
        raise HTTPException(401, "Неверный или отсутствующий API-ключ.")
    return user


@router.get("/me")
def v1_me(db: Session = Depends(get_db), user: User = Depends(get_api_user)) -> JSONResponse:
    plan = user.effective_plan()
    return JSONResponse({"email": user.email, "plan": plan, "limits": plan_limits(plan),
                         "usage": quota.usage_summary(db, user)})


@router.post("/cutout")
async def v1_cutout(request: Request, db: Session = Depends(get_db),
                    user: User = Depends(get_api_user),
                    file: UploadFile = File(...), preset: str = Form("icon-set"),
                    formats: str = Form(""), sizes: str = Form("")) -> Response:
    data = await toolapp._read_capped(file)

    overrides: dict = {"export": {}}
    if formats.strip():
        overrides["export"]["formats"] = [f.strip().lower() for f in formats.split(",") if f.strip()]
    if sizes.strip():
        try:
            overrides["export"]["sizes"] = [int(s) for s in sizes.split(",") if s.strip()]
        except ValueError:
            raise HTTPException(422, "sizes должен быть списком чисел, напр. 64,128,256")
    cfg = toolapp._cfg_from({"preset": preset, "config": overrides})

    # лимиты тарифа + списание квоты (1 вызов = 1 экспорт)
    ai = cfg.background.mode == "ai"
    quota.enforce_export(db, user, sizes=cfg.export.sizes, formats=cfg.export.formats,
                         batch_files=1, ai=ai, count=1)
    period = quota.current_period()
    if not quota.try_consume(db, user, 1, period):
        raise HTTPException(402, "Исчерпан месячный лимит экспортов. Перейдите на Pro: /pricing")

    try:
        results = pipeline.run(data, cfg, {"preset": preset, "source": file.filename})
    except Exception:  # noqa: BLE001 — нарезка не удалась → возвращаем квоту
        quota.refund(db, user, 1, period)
        raise HTTPException(422, "Не удалось обработать изображение.")
    if not results:
        quota.refund(db, user, 1, period)
        raise HTTPException(422, "Контент не найден на изображении.")

    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        multi = len(results) > 1
        for i, res in enumerate(results):
            sub = f"object_{i+1}/" if multi else ""
            for a in res.artifacts:
                zf.writestr(sub + a.name, a.data)
    return Response(bundle.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="assetforge.zip"'})
