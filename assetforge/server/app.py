"""FastAPI-приложение AssetForge.

Эндпоинты:
  GET  /                 — веб-интерфейс (SPA)
  GET  /api/presets      — список пресетов
  POST /api/upload       — загрузить файл → session_id + превью
  POST /api/analyze      — убрать фон + найти объекты (кэш по session)
  POST /api/preview      — превью одного объекта на свет/тёмном/шахматке (кэш)
  POST /api/export       — нарезать объект(ы) → ZIP
  POST /api/batch        — много файлов → общий ZIP
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from ..core import io_utils
from ..core.config import PipelineConfig, load_preset_specs, preset
from ..core.export import build_contact_sheet, package_zip
from ..core.pipeline import process_object, stage_crop, AnalyzeResult, classify_meta
from ..resources import web_dir
from .sessions import STORE

WEB_DIR = web_dir()

# Потолок размера загружаемого файла (защита от перегруза памяти/DoS).
import os as _os
MAX_UPLOAD_BYTES = int(_os.environ.get("ASSETFORGE_MAX_UPLOAD_MB", "25") or "25") * 1024 * 1024

app = FastAPI(title="AssetForge", version="0.1.0")


async def _read_capped(file: UploadFile, limit: int = MAX_UPLOAD_BYTES) -> bytes:
    """Прочитать загруженный файл по частям, не превышая limit байт (иначе 413)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 256)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"Файл слишком большой (лимит {limit // (1024*1024)} МБ).")
        chunks.append(chunk)
    return b"".join(chunks)


# --- утилиты ----------------------------------------------------------------

def _cfg_from(payload: dict[str, Any]) -> PipelineConfig:
    """Собрать конфиг: пресет как база + override-поля из UI поверх."""
    base = preset(payload["preset"]) if payload.get("preset") else PipelineConfig()
    overrides = payload.get("config") or {}
    merged = base.to_dict()
    for section, vals in overrides.items():
        if section in merged and isinstance(vals, dict):
            merged[section].update({k: v for k, v in vals.items() if v is not None})
    cfg = PipelineConfig.from_dict(merged)
    if not cfg.export.sizes:          # пустой набор размеров из UI — берём базовый
        from ..core.config import ICON_SIZES
        cfg.export.sizes = list(ICON_SIZES)
    return cfg


def _parse_index(which, count: int) -> int:
    """Безопасно разобрать object_index из запроса (клиентскую ошибку → 422, не 500)."""
    try:
        idx = int(which)
    except (TypeError, ValueError):
        raise HTTPException(422, f'object_index должен быть числом или "all", получено: {which!r}')
    return max(0, min(idx, count - 1))


def _composite_previews(img: Image.Image) -> dict[str, str]:
    """data-url'ы объекта на светлом/тёмном/шахматном фоне для проверки краёв."""
    return {
        "light": io_utils.to_data_url(_on_bg(img, (245, 246, 248, 255))),
        "dark": io_utils.to_data_url(_on_bg(img, (24, 25, 30, 255))),
        "checker": io_utils.to_data_url(_on_checker(img)),
        "raw": io_utils.to_data_url(img),
    }


def _on_bg(img: Image.Image, color) -> Image.Image:
    bg = Image.new("RGBA", img.size, color)
    bg.alpha_composite(img.convert("RGBA"))
    return bg


def _on_checker(img: Image.Image, s: int = 12) -> Image.Image:
    from PIL import ImageDraw
    w, h = img.size
    bg = Image.new("RGBA", (w, h), (200, 202, 208, 255))
    d = ImageDraw.Draw(bg)
    for y in range(0, h, s):
        for x in range(0, w, s):
            if (x // s + y // s) % 2:
                d.rectangle([x, y, x + s - 1, y + s - 1], fill=(168, 170, 178, 255))
    bg.alpha_composite(img.convert("RGBA"))
    return bg


def _thumb(img: Image.Image, box: int = 320) -> Image.Image:
    im = img.copy()
    im.thumbnail((box, box), Image.LANCZOS)
    return im


# --- API --------------------------------------------------------------------

@app.get("/api/presets")
def api_presets() -> JSONResponse:
    specs = load_preset_specs()
    items = [
        {
            "name": name,
            "title": spec.get("title", name),
            "description": spec.get("description", ""),
            "sizes": (spec.get("export") or {}).get("sizes", []),
            "formats": (spec.get("export") or {}).get("formats", []),
        }
        for name, spec in sorted(specs.items())
    ]
    return JSONResponse({"presets": items})


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)) -> JSONResponse:
    return await upload_impl(file, owner=None)


async def upload_impl(file: UploadFile, owner: str | None = None) -> JSONResponse:
    """Реализация загрузки с владельцем сессии (owner) — для квот/лимитов на пользователя."""
    data = await _read_capped(file)
    try:
        img = io_utils.load_rgba(data)
    except io_utils.ImageTooLargeError as exc:
        raise HTTPException(413, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось открыть изображение: {exc}")
    sess = STORE.create(img, filename=file.filename or "image.png", owner=owner)
    return JSONResponse({
        "session_id": sess.id,
        "filename": sess.filename,
        "width": img.size[0],
        "height": img.size[1],
        "thumb": io_utils.to_data_url(_thumb(img)),
    })


@app.post("/api/analyze")
async def api_analyze(payload: dict = None) -> JSONResponse:
    payload = payload or {}
    sess = STORE.get(payload.get("session_id", ""))
    if not sess:
        raise HTTPException(404, "Сессия не найдена (загрузите файл заново).")
    cfg = _cfg_from(payload)
    bg = sess.foreground(cfg)             # кэш
    objects = sess.objects(cfg)           # кэш
    return JSONResponse({
        "bg_mode": bg.detected_mode,
        "key_color": list(bg.key_color) if bg.key_color else None,
        "notes": bg.notes,
        "objects": [list(b) for b in objects],
        "foreground": io_utils.to_data_url(_thumb(bg.image, 420)),
        "object_thumbs": [
            io_utils.to_data_url(_thumb(bg.image.crop(b), 160)) for b in objects
        ],
        **classify_meta(bg.image, objects, bg.detected_mode),
    })


@app.post("/api/preview")
async def api_preview(payload: dict = None) -> JSONResponse:
    payload = payload or {}
    sess = STORE.get(payload.get("session_id", ""))
    if not sess:
        raise HTTPException(404, "Сессия не найдена.")
    cfg = _cfg_from(payload)
    bg = sess.foreground(cfg)             # кэш
    objects = sess.objects(cfg)           # кэш
    if not objects:
        raise HTTPException(422, "Контент не найден — ослабьте порог/проверьте режим фона.")
    idx = _parse_index(payload.get("object_index", 0), len(objects))
    cropped = stage_crop(bg.image, objects[idx], cfg)   # дёшево

    # маленькое превью-размеры из выбранного набора (для «как будет в иконке»)
    from ..core.resize import resize_to
    square = cfg.crop.square and cfg.crop.fit != "width"
    sample_sizes = sorted(set(cfg.export.sizes))[:7]
    samples = [
        {"size": s, "url": io_utils.to_data_url(resize_to(cropped, s, cfg.resize, square))}
        for s in sample_sizes
    ]
    return JSONResponse({
        "object_index": idx,
        "bbox": list(objects[idx]),
        "cropped": _composite_previews(_thumb(cropped, 360)),
        "samples": samples,
        "notes": bg.notes,
        "bg_mode": bg.detected_mode,
    })


@app.post("/api/export")
async def api_export(payload: dict = None) -> Response:
    payload = payload or {}
    sess = STORE.get(payload.get("session_id", ""))
    if not sess:
        raise HTTPException(404, "Сессия не найдена.")
    cfg = _cfg_from(payload)
    bg = sess.foreground(cfg)
    objects = sess.objects(cfg)
    if not objects:
        raise HTTPException(422, "Контент не найден.")

    which = payload.get("object_index", "all")
    if which in ("all", None):
        indices = list(range(len(objects)))
    else:
        indices = [_parse_index(which, len(objects))]

    multi = len(indices) > 1 or len(objects) > 1   # считаем один раз (не O(n²) в цикле)
    analysis = AnalyzeResult(bg.image, bg, objects, cfg, {})
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in indices:
            res = process_object(analysis, i, cfg, {"preset": payload.get("preset", "custom"),
                                                    "source": sess.filename})
            sub = f"object_{i+1}/" if multi else ""
            for a in res.artifacts:
                zf.writestr(sub + a.name, a.data)
    bundle.seek(0)
    fname = Path(sess.filename).stem + "_assetforge.zip"
    return Response(bundle.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/api/batch")
async def api_batch(files: list[UploadFile] = File(...), preset_name: str = Form("icon-set"),
                    config: str = Form("{}")) -> Response:
    """Много файлов → обработка каждого → общий ZIP (папка на файл)."""
    import json
    from ..core import pipeline

    overrides = json.loads(config or "{}")
    cfg = _cfg_from({"preset": preset_name, "config": overrides})

    bundle = io.BytesIO()
    report: list[str] = []
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            data = await _read_capped(f)
            stem = Path(f.filename or "image").stem
            try:
                results = pipeline.run(data, cfg, {"preset": preset_name, "source": f.filename})
            except Exception as exc:  # noqa: BLE001
                report.append(f"{f.filename}: ОШИБКА — {exc}")
                continue
            for i, res in enumerate(results):
                sub = f"{stem}/object_{i+1}/" if len(results) > 1 else f"{stem}/"
                for a in res.artifacts:
                    zf.writestr(sub + a.name, a.data)
            report.append(f"{f.filename}: {len(results)} объект(ов)")
        zf.writestr("_report.txt", "\n".join(report) + "\n")
    bundle.seek(0)
    return Response(bundle.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="assetforge_batch.zip"'})


# --- статика / SPA ----------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    idx = WEB_DIR / "index.html"
    if idx.exists():
        return HTMLResponse(idx.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>AssetForge</h1><p>web/ не найден</p>")


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
