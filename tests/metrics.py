"""Метрики для проверки результата по сути, а не пиксель-в-пиксель."""
from __future__ import annotations

import numpy as np
from PIL import Image


def alpha_coverage(im: Image.Image, thr: int = 16) -> float:
    """Доля пикселей с alpha > thr (0..1)."""
    a = np.asarray(im.convert("RGBA"))[:, :, 3]
    return float((a > thr).mean())


def content_bbox(im: Image.Image, thr: int = 16):
    a = np.asarray(im.convert("RGBA"))[:, :, 3]
    mask = a > thr
    ys = np.where(mask.any(axis=1))[0]
    xs = np.where(mask.any(axis=0))[0]
    if len(ys) == 0 or len(xs) == 0:
        return None
    return int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1


def border_opaque_fraction(im: Image.Image, band: int = 6, thr: int = 16) -> float:
    """Доля непрозрачных пикселей по рамке (после удаления фона должна быть ~0)."""
    a = np.asarray(im.convert("RGBA"))[:, :, 3]
    h, w = a.shape
    border = np.concatenate([
        a[:band, :].ravel(), a[-band:, :].ravel(),
        a[:, :band].ravel(), a[:, -band:].ravel(),
    ])
    return float((border > thr).mean())


def mean_color_in_mask(im: Image.Image, thr: int = 200):
    """Средний RGB в непрозрачной области объекта."""
    arr = np.asarray(im.convert("RGBA")).astype(np.float32)
    m = arr[:, :, 3] > thr
    if m.sum() == 0:
        return (0.0, 0.0, 0.0)
    rgb = arr[:, :, :3][m]
    return tuple(float(v) for v in rgb.mean(axis=0))


def green_excess(im: Image.Image, thr: int = 200) -> float:
    """Средний «избыток зелёного» G-max(R,B) в непрозрачной области (для despill)."""
    arr = np.asarray(im.convert("RGBA")).astype(np.float32)
    m = arr[:, :, 3] > thr
    if m.sum() == 0:
        return 0.0
    r, g, b = arr[:, :, 0][m], arr[:, :, 1][m], arr[:, :, 2][m]
    return float(np.clip(g - np.maximum(r, b), 0, None).mean())


def has_soft_edge(im: Image.Image) -> bool:
    """Есть ли полупрозрачные пиксели (антиалиасный край), а не только 0/255."""
    a = np.asarray(im.convert("RGBA"))[:, :, 3]
    return bool(((a > 8) & (a < 247)).sum() > 0)
