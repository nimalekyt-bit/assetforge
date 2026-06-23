"""Качественный ресайз под целевые размеры (квадраты и прямоугольные холсты W×H)."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

from . import io_utils
from .config import ResizeConfig

_RESAMPLE = {
    "lanczos": Image.LANCZOS,
    "bicubic": Image.BICUBIC,
    "nearest": Image.NEAREST,
}


def resize_to(im: Image.Image, size: int, cfg: ResizeConfig, square: bool = True) -> Image.Image:
    """Отресайзить до целевого размера.

    square=True → выход size×size БЕЗ искажения пропорций: непропорциональный
    источник сперва вписывается в квадрат с прозрачным паддингом (letterbox), и
    только потом масштабируется. Это убирает растяжение fit="none"+square.
    square=False → масштаб по ширине = size с сохранением пропорций (для вордмарков).
    """
    resample = _RESAMPLE.get(cfg.resample, Image.LANCZOS)
    w, h = im.size
    if w <= 0 or h <= 0:
        raise ValueError(f"Пустое изображение для ресайза: {w}×{h}")

    if square:
        # letterbox в квадрат + ресайз (io_utils._square не искажает пропорции)
        out = io_utils._square(im, size, resample=resample)
    else:
        new_h = max(1, round(h * size / w))
        out = im.resize((size, new_h), resample)

    # лёгкая резкость при сильном уменьшении, чтобы мелкие иконки не мылились
    if cfg.unsharp and size <= cfg.unsharp_below and max(w, h) > size * 1.5:
        out = out.filter(ImageFilter.UnsharpMask(radius=0.6, percent=80, threshold=0))
    return out


def render_target(im: Image.Image, w: int, h: int, fit: str = "contain",
                  bg=None, cfg: ResizeConfig | None = None, focus=None) -> Image.Image:
    """Отрендерить подготовленный объект в прямоугольный холст W×H.

    fit:
      - ``pad``/``contain`` — вписать целиком с прозрачными полями (scale=min);
      - ``cover`` — заполнить рамку и обрезать лишнее (scale=max), окно позиционируется
        по ``focus`` (нормированный центр значимости [0..1]); тупого центра нет;
      - ``stretch`` — растянуть точно в W×H (искажает пропорции).
    bg: None=прозрачный · [r,g,b(,a)]=сплошной · ``"auto"``=доминирующий цвет края источника.
    """
    cfg = cfg or ResizeConfig()
    resample = _RESAMPLE.get(cfg.resample, Image.LANCZOS)
    im = im.convert("RGBA")
    bw, bh = im.size
    w, h = max(1, int(w)), max(1, int(h))
    if bw <= 0 or bh <= 0:
        raise ValueError(f"Пустое изображение для таргета: {bw}×{bh}")

    if fit == "stretch":
        canvas = im.resize((w, h), resample)
    else:
        scale = (max if fit == "cover" else min)(w / bw, h / bh)
        nw, nh = max(1, round(bw * scale)), max(1, round(bh * scale))
        scaled = im.resize((nw, nh), resample)
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if fit == "cover":
            fx, fy = focus if focus else (0.5, 0.5)
            left = max(0, min(int(round(fx * nw - w / 2)), nw - w))
            top = max(0, min(int(round(fy * nh - h / 2)), nh - h))
            canvas.alpha_composite(scaled.crop((left, top, left + w, top + h)))
        else:  # contain/pad — центрируем с полями
            canvas.alpha_composite(scaled, ((w - nw) // 2, (h - nh) // 2))

    if cfg.unsharp and max(bw, bh) > max(w, h) * 1.5 and max(w, h) <= cfg.unsharp_below:
        canvas = canvas.filter(ImageFilter.UnsharpMask(radius=0.6, percent=80, threshold=0))

    bg_color = _resolve_bg(bg, im)
    if bg_color is not None:
        base = Image.new("RGBA", canvas.size, bg_color)
        base.alpha_composite(canvas)
        canvas = base
    return canvas


def _resolve_bg(bg, src: Image.Image):
    """None → нет фона; список/кортеж → сплошной; 'auto' → доминирующий цвет края источника."""
    if bg is None:
        return None
    if isinstance(bg, str):
        if bg.lower() != "auto":
            return None
        a = np.asarray(src.convert("RGBA"))
        h, w = a.shape[:2]
        b = max(1, int(min(h, w) * 0.06))
        edge = np.concatenate([a[:b].reshape(-1, 4), a[-b:].reshape(-1, 4),
                               a[:, :b].reshape(-1, 4), a[:, -b:].reshape(-1, 4)])
        op = edge[edge[:, 3] > 200]
        if len(op) == 0:
            return (255, 255, 255, 255)
        med = np.median(op[:, :3], axis=0).round().astype(int)
        return (int(med[0]), int(med[1]), int(med[2]), 255)
    c = list(bg)
    if len(c) >= 4:
        return (int(c[0]), int(c[1]), int(c[2]), int(c[3]))
    if len(c) == 3:
        return (int(c[0]), int(c[1]), int(c[2]), 255)
    return None
