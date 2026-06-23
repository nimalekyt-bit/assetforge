"""Эффекты подложки/обводки (Tier 0/1): die-cut контур, тень, скругление, рамка, фон.

Все функции — чистые: на входе и выходе PIL.Image в режиме RGBA, исходник НЕ
мутируется (возвращается НОВОЕ изображение). Размеры эффектов адаптивные —
проценты от меньшей стороны, а не фикс-пиксели, поэтому одинаково смотрятся и на
иконке 64px, и на баннере 4000px. Где эффект может вылезти за края (контур, тень)
холст расширяется и контент центрируется, чтобы ничего не обрезалось.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

Color = tuple[int, ...]


# --- общие утилиты ---------------------------------------------------------

def _rgba(color: Color) -> tuple[int, int, int, int]:
    """Привести (r,g,b) или (r,g,b,a) к 4-кортежу uint8 (alpha по умолчанию 255)."""
    c = tuple(int(v) for v in color)
    if len(c) == 3:
        c = c + (255,)
    if len(c) != 4:
        raise ValueError(f"Ожидался цвет из 3 или 4 компонент, получено: {color!r}")
    return tuple(max(0, min(255, v)) for v in c)  # type: ignore[return-value]


def _as_rgba(im: Image.Image) -> Image.Image:
    """Гарантировать RGBA, не трогая исходник (convert даёт копию даже при совпадении)."""
    return im if im.mode == "RGBA" else im.convert("RGBA")


def _alpha(im: Image.Image) -> np.ndarray:
    """Канал alpha как (H, W) uint8 (read-only view достаточно — мы только читаем)."""
    return np.asarray(im)[:, :, 3]


def _is_degenerate(im: Image.Image) -> bool:
    """1×1 (или вырожденный) холст — эффекты не имеют смысла, возвращаем как есть."""
    w, h = im.size
    return w <= 1 or h <= 1


def _is_empty(a: np.ndarray) -> bool:
    """Полностью прозрачный слой — нечего обводить/затенять."""
    return a.size == 0 or int(a.max()) == 0


def _dilate_alpha(a: np.ndarray, r: int) -> np.ndarray:
    """Серая дилатация alpha на r итераций (8-связность, max по соседям).

    Аналог detect._dilate, но не бинарный: берём max по 8 сдвигам, чтобы сохранить
    сглаженный (анти-алиас) внешний край силуэта вместо «лесенки».
    """
    m = a
    for _ in range(int(r)):
        d = m.copy()
        d[1:, :] = np.maximum(d[1:, :], m[:-1, :])
        d[:-1, :] = np.maximum(d[:-1, :], m[1:, :])
        d[:, 1:] = np.maximum(d[:, 1:], m[:, :-1])
        d[:, :-1] = np.maximum(d[:, :-1], m[:, 1:])
        d[1:, 1:] = np.maximum(d[1:, 1:], m[:-1, :-1])
        d[:-1, :-1] = np.maximum(d[:-1, :-1], m[1:, 1:])
        d[1:, :-1] = np.maximum(d[1:, :-1], m[:-1, 1:])
        d[:-1, 1:] = np.maximum(d[:-1, 1:], m[1:, :-1])
        m = d
    return m


def _scale_alpha(a: np.ndarray, factor: int) -> np.ndarray:
    """Помножить alpha на factor/255 (для полупрозрачного цвета обводки/тени)."""
    if factor >= 255:
        return a
    return (a.astype(np.uint16) * factor // 255).astype(np.uint8)


def _solid_layer(alpha: np.ndarray, rgba: tuple[int, int, int, int]) -> Image.Image:
    """Сплошной цвет rgba с заданной маской alpha → RGBA-изображение того же размера."""
    h, w = alpha.shape
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[..., 0] = rgba[0]
    out[..., 1] = rgba[1]
    out[..., 2] = rgba[2]
    out[..., 3] = _scale_alpha(alpha, rgba[3])
    return Image.fromarray(out, "RGBA")


# --- эффекты ---------------------------------------------------------------

def add_outline(im: Image.Image, width_pct: float = 3.0,
                color: Color = (255, 255, 255, 255)) -> Image.Image:
    """«Die-cut» контур по силуэту объекта (стикер-обводка).

    Толщина адаптивная: t = max(1, round(min(W,H) * width_pct/100)). Альфа-маску
    объекта расширяем серой дилатацией на t, заливаем color и кладём ПОД объект —
    видимым остаётся кольцо «дилатация − исходный силуэт». Холст расширяется на t с
    каждой стороны (контент центрируется), чтобы контур не обрезался по краям.
    """
    im = _as_rgba(im)
    if _is_degenerate(im):
        return im
    w, h = im.size
    a = _alpha(im)
    if _is_empty(a):
        return im

    t = max(1, round(min(w, h) * width_pct / 100.0))
    nw, nh = w + 2 * t, h + 2 * t

    padded = np.zeros((nh, nw), dtype=np.uint8)
    padded[t:t + h, t:t + w] = a
    ring = _dilate_alpha(padded, t)

    base = _solid_layer(ring, _rgba(color))
    obj = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    obj.paste(im, (t, t))
    return Image.alpha_composite(base, obj)


def drop_shadow(im: Image.Image, dx: int = 0, dy: int = 6, blur: int = 10,
                color: Color = (0, 0, 0, 150), grow: int = 0) -> Image.Image:
    """Мягкая тень под объектом.

    Силуэт (alpha) → залить color → опционально «раздуть» на grow → GaussianBlur →
    сместить на (dx, dy) → положить ПОД объект. Радиус размытия, смещение и grow
    масштабируются адаптивно (k = min(W,H)/512), поэтому тень пропорциональна размеру
    картинки. Холст расширяется со всех сторон ровно настолько, чтобы размытая
    смещённая тень полностью влезла.
    """
    im = _as_rgba(im)
    if _is_degenerate(im):
        return im
    w, h = im.size
    a = _alpha(im)
    if _is_empty(a):
        return im

    k = min(w, h) / 512.0
    blur_px = max(0.0, blur * k)
    grow_px = max(0, round(grow * k))
    ox, oy = round(dx * k), round(dy * k)

    spread = grow_px + int(math.ceil(blur_px * 3)) + 1
    pad = spread + max(abs(ox), abs(oy))
    nw, nh = w + 2 * pad, h + 2 * pad

    sil = np.zeros((nh, nw), dtype=np.uint8)
    sil[pad + oy:pad + oy + h, pad + ox:pad + ox + w] = a  # сразу со смещением
    if grow_px > 0:
        sil = _dilate_alpha(sil, grow_px)

    shadow = _solid_layer(sil, _rgba(color))
    if blur_px > 0:
        shadow = shadow.filter(ImageFilter.GaussianBlur(blur_px))

    obj = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    obj.paste(im, (pad, pad))
    return Image.alpha_composite(shadow, obj)


def rounded_corners(im: Image.Image, radius_pct: float = 18.0) -> Image.Image:
    """Скруглить прямоугольный холст: умножить alpha на маску rounded_rectangle.

    radius = min(W,H) * radius_pct/100 (с потолком в половину меньшей стороны, иначе
    скругление вырождается). Размер холста не меняется — эффект только убирает углы.
    """
    im = _as_rgba(im)
    if _is_degenerate(im):
        return im
    w, h = im.size

    radius = int(round(min(w, h) * radius_pct / 100.0))
    radius = max(0, min(radius, min(w, h) // 2))

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)

    arr = np.array(im)  # writable copy — исходник не трогаем
    arr[:, :, 3] = (arr[:, :, 3].astype(np.uint16) * np.asarray(mask) // 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def add_border(im: Image.Image, width_pct: float = 4.0,
               color: Color = (255, 255, 255, 255)) -> Image.Image:
    """Сплошная рамка по периметру холста поверх объекта.

    Толщина адаптивная: t = max(1, round(min(W,H) * width_pct/100)) (не толще
    половины меньшей стороны). Рамка рисуется внутрь от краёв холста, размер не
    меняется.
    """
    im = _as_rgba(im)
    if _is_degenerate(im):
        return im
    w, h = im.size

    t = max(1, round(min(w, h) * width_pct / 100.0))
    t = min(t, min(w, h) // 2 or 1)
    rgba = _rgba(color)

    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([0, 0, w - 1, t - 1], fill=rgba)          # верх
    d.rectangle([0, h - t, w - 1, h - 1], fill=rgba)      # низ
    d.rectangle([0, 0, t - 1, h - 1], fill=rgba)          # лево
    d.rectangle([w - t, 0, w - 1, h - 1], fill=rgba)      # право
    return Image.alpha_composite(im, layer)


def add_background(im: Image.Image, bg: Color) -> Image.Image:
    """Подложить сплошной фон bg = (r,g,b) | (r,g,b,a) под объект.

    Размер холста сохраняется; объект композитится поверх залитого фона.
    """
    im = _as_rgba(im)
    if _is_degenerate(im):
        return im
    w, h = im.size
    base = Image.new("RGBA", (w, h), _rgba(bg))
    return Image.alpha_composite(base, im)


# --- self-тест -------------------------------------------------------------

if __name__ == "__main__":
    from pathlib import Path

    def _circle(size: int = 200, fill=(70, 140, 255, 255)) -> Image.Image:
        """Синтетический RGBA-кружок на прозрачном фоне."""
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        m = size // 10
        ImageDraw.Draw(im).ellipse([m, m, size - 1 - m, size - 1 - m], fill=fill)
        return im

    src = _circle()
    effects = [
        ("original", src),
        ("outline", add_outline(src, width_pct=6.0, color=(255, 255, 255, 255))),
        ("drop_shadow", drop_shadow(src, dx=0, dy=12, blur=14, color=(0, 0, 0, 160))),
        ("rounded", rounded_corners(src, radius_pct=25.0)),
        ("border", add_border(src, width_pct=5.0, color=(255, 80, 80, 255))),
        ("background", add_background(src, (245, 230, 180))),
    ]

    # краевые случаи не должны падать
    tiny = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    blank = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    assert add_outline(tiny).size == (1, 1)
    assert drop_shadow(blank).size == (64, 64)
    assert add_outline(blank).size == (64, 64)

    # сетка «до/после»: каждый эффект на нейтрально-сером с подписью
    cell, cols = 240, 3
    rows = (len(effects) + cols - 1) // cols
    grid = Image.new("RGBA", (cols * cell, rows * cell), (210, 210, 214, 255))
    draw = ImageDraw.Draw(grid)
    sizes = []
    for i, (name, img) in enumerate(effects):
        sizes.append((name, img.size))
        thumb = img.copy()
        thumb.thumbnail((cell - 40, cell - 60), Image.LANCZOS)
        cx = (i % cols) * cell + (cell - thumb.width) // 2
        cy = (i // cols) * cell + (cell - 20 - thumb.height) // 2 + 10
        grid.alpha_composite(thumb, (cx, cy))
        draw.text(((i % cols) * cell + 10, (i // cols) * cell + cell - 18),
                  f"{name} {img.size[0]}x{img.size[1]}", fill=(30, 30, 30, 255))

    out_path = Path(r"E:\photovirez\design\effects_demo.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    grid.convert("RGB").save(out_path)

    print("OK effects self-test")
    for name, sz in sizes:
        print(f"  {name:12s} -> {sz[0]}x{sz[1]}")
    print(f"demo saved: {out_path}")
