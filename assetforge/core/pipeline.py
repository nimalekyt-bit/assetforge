"""Оркестратор: load → remove bg → detect → crop → resize → export.

Стадии намеренно разделены и кэшируемы по отдельности:
  - :func:`stage_background` — только удаление фона (UI показывает «фон удалён хорошо/плохо»);
  - :func:`stage_detect`     — поиск объектов/bbox поверх результата фона;
  - :func:`stage_crop`       — обрезка конкретного объекта;
  - :func:`stage_export`     — нарезка размеров и форматов выбранного объекта.

Это позволяет серверу кэшировать промежуточные RGBA/mask/bbox по session_id и не
гонять весь пайплайн заново на каждый /preview и /export.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image

from . import crop as crop_mod
from . import detect as detect_mod
from .background import BackgroundResult, remove_background
from .config import PipelineConfig
from .export import ExportResult, build_export
from .io_utils import load_rgba


@dataclass
class AnalyzeResult:
    """Результат анализа: фон убран + найдены объекты (для предпросмотра в UI)."""

    foreground: Image.Image                 # RGBA после удаления фона
    background: BackgroundResult
    objects: list[tuple[int, int, int, int]]
    config: PipelineConfig
    meta: dict = field(default_factory=dict)


# --- отдельные стадии ------------------------------------------------------

def stage_background(im: Image.Image, cfg: PipelineConfig) -> BackgroundResult:
    return remove_background(im, cfg.background)


def stage_detect(fg: Image.Image, cfg: PipelineConfig) -> list[tuple[int, int, int, int]]:
    return detect_mod.split_objects(
        fg,
        threshold=cfg.background.trim_alpha_threshold,
        min_area=cfg.crop.min_object_area,
        mode=cfg.crop.split,
        merge_distance=cfg.crop.merge_distance,
        grid_rows=cfg.crop.grid_rows,
        grid_cols=cfg.crop.grid_cols,
    )


def stage_crop(fg: Image.Image, bbox, cfg: PipelineConfig) -> Image.Image:
    return crop_mod.apply_crop(fg, bbox, cfg.crop)


def stage_export(cropped: Image.Image, cfg: PipelineConfig, meta: dict | None = None) -> ExportResult:
    square = cfg.crop.square and cfg.crop.fit != "width"
    return build_export(cropped, cfg.export, cfg.resize, square=square, meta=meta)


# --- удобные обёртки -------------------------------------------------------

def analyze(source, cfg: PipelineConfig | None = None) -> AnalyzeResult:
    """Загрузить, убрать фон, найти объекты. Без нарезки (быстро, для предпросмотра)."""
    cfg = cfg or PipelineConfig()
    im = load_rgba(source)
    bg = stage_background(im, cfg)
    objects = stage_detect(bg.image, cfg)
    meta = {
        "bg_mode": bg.detected_mode,
        "objects": len(objects),
        "size": list(im.size),
    }
    meta.update(classify_meta(bg.image, objects, bg.detected_mode))
    return AnalyzeResult(bg.image, bg, objects, cfg, meta)


def classify_meta(fg: Image.Image, objects, bg_mode) -> dict:
    """Авто-классификация типа ассета и рекомендация пресета (опционально, graceful)."""
    try:
        from .classify import classify_asset
        c = classify_asset(fg, objects, bg_mode)
        return {
            "asset_kind": c.get("kind"),
            "suggested_preset": c.get("suggested_preset"),
            "classify_confidence": round(float(c.get("confidence", 0)), 2),
            "classify_reasons": c.get("reasons", []),
        }
    except Exception:  # noqa: BLE001 — классификатор опционален, не должен ронять анализ
        return {}


def process_object(
    analysis: AnalyzeResult,
    object_index: int = 0,
    cfg: PipelineConfig | None = None,
    extra_meta: dict | None = None,
) -> ExportResult:
    """Обрезать и нарезать один найденный объект из результата :func:`analyze`."""
    cfg = cfg or analysis.config
    if not analysis.objects:
        raise ValueError("Контент не найден (объектов 0).")
    object_index = max(0, min(object_index, len(analysis.objects) - 1))
    bbox = analysis.objects[object_index]
    cropped = stage_crop(analysis.foreground, bbox, cfg)
    meta = {
        "preset": extra_meta.get("preset", "custom") if extra_meta else "custom",
        "bg_mode": analysis.background.detected_mode,
        "objects": len(analysis.objects),
        "object_index": object_index,
        "bbox": list(bbox),
    }
    if extra_meta:
        meta.update(extra_meta)
    return stage_export(cropped, cfg, meta=meta)


def run(source, cfg: PipelineConfig | None = None, extra_meta: dict | None = None) -> list[ExportResult]:
    """Полный прогон: проанализировать и нарезать ВСЕ найденные объекты."""
    cfg = cfg or PipelineConfig()
    analysis = analyze(source, cfg)
    results: list[ExportResult] = []
    if not analysis.objects:          # контента не нашли — пустой результат, без падения
        return results
    n = len(analysis.objects)
    for i in range(n):
        meta = dict(extra_meta or {})
        if n > 1:
            meta["object_index"] = i
        results.append(process_object(analysis, i, cfg, meta))
    return results
