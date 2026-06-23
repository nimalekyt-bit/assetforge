"""Обрезка контента, паддинг и вписывание в холст."""
from __future__ import annotations

from PIL import Image

from .config import CropConfig
from .detect import BBox


def crop_to_bbox(im: Image.Image, bbox: BBox, padding_pct: float = 0.0) -> Image.Image:
    """Обрезать по bbox с паддингом (% от стороны bbox), не вылезая за пределы картинки."""
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    pad = round(max(bw, bh) * padding_pct / 100.0)
    W, H = im.size
    cx0 = max(0, x0 - pad)
    cy0 = max(0, y0 - pad)
    cx1 = min(W, x1 + pad)
    cy1 = min(H, y1 + pad)
    return im.crop((cx0, cy0, cx1, cy1))


def fit_square(im: Image.Image, align: str = "center") -> Image.Image:
    """Вписать в квадратный прозрачный холст без искажений (сторона = max(w,h))."""
    w, h = im.size
    side = max(w, h, 1)   # не допускаем вырожденный 0×0 холст
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    ox, oy = _offset(side, side, w, h, align)
    canvas.paste(im, (ox, oy), im)
    return canvas


def apply_crop(im: Image.Image, bbox: BBox, cfg: CropConfig) -> Image.Image:
    """Полный шаг кадрирования по конфигу: обрезка + (опц.) вписывание в квадрат.

    Согласовано с экспортом: при ``square=True`` (и ``fit`` ≠ ``width``) кроп
    ВПИСЫВАЕТСЯ в квадрат прозрачным паддингом (letterbox) — без растяжения
    пропорций, даже когда ``fit="none"``. Так PNG и ICO/ICNS получают один и тот
    же квадратный источник.
    """
    out = crop_to_bbox(im, bbox, cfg.padding_pct)
    if cfg.fit == "width":
        # для вордмарков: квадрат не делаем, оставляем пропорции как есть
        return out
    if cfg.square:
        out = fit_square(out, cfg.align)
    return out


def _offset(cw: int, ch: int, w: int, h: int, align: str) -> tuple[int, int]:
    ox = (cw - w) // 2
    oy = (ch - h) // 2
    if align == "top":
        oy = 0
    elif align == "bottom":
        oy = ch - h
    elif align == "left":
        ox = 0
    elif align == "right":
        ox = cw - w
    return ox, oy
