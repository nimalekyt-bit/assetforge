"""Конфигурация пайплайна: dataclass-настройки + готовые пресеты.

Любой шаг можно отключить/настроить через :class:`PipelineConfig`. Конфиг сериализуется
в обычный dict (``to_dict`` / ``from_dict``), что удобно гонять между CLI, сервером и web-UI.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# --- наборы размеров -------------------------------------------------------

ICON_SIZES = [16, 32, 48, 64, 128, 256, 512]
LAUNCHER_SIZES = [256, 512, 1024]
WEB_LOGO_WIDTHS = [256, 512, 1024, 2048]  # для несквадратных лого — по ширине

# размеры, упаковываемые в один .ico (Windows ограничивает 256)
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
# размеры, которые понимает .icns
ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]


@dataclass
class BackgroundConfig:
    """Удаление фона."""

    mode: str = "auto"          # auto | alpha | white | solid | chroma | ai | none
    key_color: list[int] | None = None  # для solid/chroma: [r,g,b]; None = авто из рамки
    tolerance: int = 32         # радиус внутреннего порога (полная прозрачность)
    softness: int = 24          # ширина мягкого края (антиалиасинг)
    despill: bool = True        # подавление цветной каймы для хромакея
    despill_strength: float = 1.0   # сила despill 0..1.5 (ползунок в UI)
    trim_alpha_threshold: int = 16  # ниже этого alpha считаем «мусором» при обрезке


@dataclass
class CropConfig:
    """Поиск контента и обрезка."""

    split: str = "auto"         # single | auto | objects | grid | xycut — разделение на объекты
    padding_pct: float = 6.0    # паддинг вокруг контента, % от стороны bbox
    fit: str = "contain"        # contain (вписать в квадрат) | width (по ширине) | none
    square: bool = True         # вписывать в квадратный холст
    align: str = "center"       # center | top | bottom | left | right
    min_object_area: int = 16   # минимальная площадь объекта (px) при split
    merge_distance: int = 0     # «склейка» близких частей объекта (px) для auto/objects
    grid_rows: int = 0          # сетка: строк (mode=grid)
    grid_cols: int = 0          # сетка: столбцов (mode=grid)
    focus: list | None = None   # [fx,fy] в [0..1] — ручной центр для cover-кропа (override saliency)


@dataclass
class ResizeConfig:
    """Качество ресайза."""

    resample: str = "lanczos"   # lanczos | bicubic | nearest
    unsharp: bool = True        # лёгкая резкость при сильном даунскейле
    unsharp_below: int = 96     # применять unsharp для размеров <= этого


@dataclass
class NamedTarget:
    """Прямоугольный целевой холст W×H (соцсети, стор, печать, email, баннеры).

    fit: ``pad``/``contain`` (вписать с полями) | ``cover`` (заполнить+обрезать,
    с учётом saliency) | ``stretch`` (растянуть). bg: None=прозрачный |
    [r,g,b(,a)] = сплошной | ``"auto"`` = доминирующий цвет края источника.
    """
    name: str
    w: int
    h: int
    fit: str = "contain"
    bg: object = None
    format: str = "png"


@dataclass
class ExportConfig:
    """Что и в каком виде выгружать."""

    sizes: list[int] = field(default_factory=lambda: list(ICON_SIZES))
    formats: list[str] = field(default_factory=lambda: ["png"])  # png ico icns webp svg jpg avif
    make_contact_sheet: bool = True
    make_zip: bool = True
    basename: str = "icon"
    # WebP: по умолчанию визуально-без-потерь lossy q=90 (намного легче, чем
    # lossless/100). Поставь webp_lossless=True для точной копии.
    webp_lossless: bool = False
    webp_quality: int = 90
    png_optimize: bool = True   # сжимать PNG посильнее (optimize=True)
    # --- прямоугольные таргеты W×H (фундамент несквадратных ассетов) ---
    targets: list = field(default_factory=list)   # список dict|NamedTarget: {name,w,h,fit,bg,format}
    retina: bool = False        # дублировать каждый таргет ×2 с суффиксом @2x
    jpg_quality: int = 90       # качество JPG (для format=jpg)
    jpg_bg: list = field(default_factory=lambda: [255, 255, 255])  # подложка под JPG (нет alpha)
    # эффекты подложки, применяются к объекту ДО рендера размеров/таргетов:
    # [{type: outline|shadow|rounded|border|background, ...params}]
    effects: list = field(default_factory=list)


@dataclass
class PipelineConfig:
    """Полная конфигурация одного прогона."""

    background: BackgroundConfig = field(default_factory=BackgroundConfig)
    crop: CropConfig = field(default_factory=CropConfig)
    resize: ResizeConfig = field(default_factory=ResizeConfig)
    export: ExportConfig = field(default_factory=ExportConfig)

    # ---- сериализация ----
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PipelineConfig":
        data = data or {}
        return cls(
            background=BackgroundConfig(**(data.get("background") or {})),
            crop=CropConfig(**(data.get("crop") or {})),
            resize=ResizeConfig(**(data.get("resize") or {})),
            export=ExportConfig(**(data.get("export") or {})),
        )


# --- пресеты (расширяемые, из presets/*.json) ------------------------------

import json

from ..resources import presets_dir as _presets_dir

# каталог с JSON-пресетами: assetforge/presets/ (или из бандла .exe)
PRESETS_DIR = _presets_dir()

# дефолты на случай отсутствия файлов (первый запуск/сборка без data-файлов)
_BUILTIN_PRESETS: dict[str, dict[str, Any]] = {
    "icon-set": {
        "title": "Icon set (16–512)",
        "export": {"sizes": ICON_SIZES, "formats": ["png", "ico", "icns", "webp"]},
        "crop": {"fit": "contain", "square": True},
    },
    "launcher": {
        "title": "Launcher / App",
        "export": {"sizes": LAUNCHER_SIZES, "formats": ["png", "ico", "icns"]},
        "crop": {"fit": "contain", "square": True},
    },
    "web-logo": {
        "title": "Web logo (wordmark, по ширине)",
        "export": {"sizes": WEB_LOGO_WIDTHS, "formats": ["png", "webp", "svg"]},
        "crop": {"fit": "width", "square": False},
    },
    "favicon": {
        "title": "Favicon",
        "export": {"sizes": [16, 32, 48, 64, 180, 192, 512], "formats": ["png", "ico"]},
        "crop": {"fit": "contain", "square": True},
    },
    "all": {
        "title": "Всё сразу",
        "export": {
            "sizes": sorted(set(ICON_SIZES + LAUNCHER_SIZES)),
            "formats": ["png", "ico", "icns", "webp", "svg"],
        },
    },
}


def _config_from_spec(spec: dict[str, Any]) -> PipelineConfig:
    """Собрать PipelineConfig из dict-описания пресета (только заданные поля)."""
    return PipelineConfig.from_dict(
        {k: spec[k] for k in ("background", "crop", "resize", "export") if k in spec}
    )


def load_preset_specs() -> dict[str, dict[str, Any]]:
    """Все доступные пресеты: JSON-файлы из PRESETS_DIR перекрывают встроенные."""
    specs: dict[str, dict[str, Any]] = {k: dict(v) for k, v in _BUILTIN_PRESETS.items()}
    if PRESETS_DIR.is_dir():
        for fp in sorted(PRESETS_DIR.glob("*.json")):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            specs[data.get("name", fp.stem)] = data
    return specs


def preset(name: str) -> PipelineConfig:
    """Готовый конфиг по имени пресета (JSON или встроенный)."""
    name = (name or "icon-set").lower()
    specs = load_preset_specs()
    # синонимы
    alias = {"icons": "icon-set", "icon": "icon-set", "logo": "web-logo",
             "wordmark": "web-logo", "app": "launcher", "everything": "all"}
    name = alias.get(name, name)
    if name not in specs:
        raise ValueError(f"Неизвестный пресет: {name!r} (есть: {', '.join(sorted(specs))})")
    return _config_from_spec(specs[name])


def preset_names() -> list[str]:
    return sorted(load_preset_specs().keys())


# совместимость со старым импортом
PRESET_NAMES = sorted(_BUILTIN_PRESETS.keys())
