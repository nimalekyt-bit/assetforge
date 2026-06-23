"""Загрузка изображений в RGBA и сохранение в разные форматы."""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path

from PIL import Image

from .config import ICNS_SIZES, ICO_SIZES

# крупнее этого по большей стороне — апскейл не нужен, понижаем для скорости анализа
ANALYZE_MAX = 1600

# Защита от «декомпрессионных бомб»: потолок числа пикселей декодируемого изображения.
# Маленький файл может разворачиваться в гигапиксели и съесть всю память — режем по заголовку.
MAX_IMAGE_PIXELS = int(os.environ.get("ASSETFORGE_MAX_IMAGE_PIXELS", str(50_000_000)) or 50_000_000)
# поднимаем порог самого Pillow согласованно (с запасом ×2, как делает Pillow для ошибки)
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class ImageTooLargeError(ValueError):
    """Изображение превышает лимит по числу пикселей (защита от бомб/перегруза памяти)."""


def load_rgba(source) -> Image.Image:
    """Открыть из пути / файлоподобного / bytes / готового PIL.Image и привести к RGBA.

    Перед полным декодированием проверяет размер по заголовку — защита от
    «декомпрессионных бомб» и чрезмерного расхода памяти.
    """
    if isinstance(source, Image.Image):
        _check_pixels(source.size)
        return source if source.mode == "RGBA" else source.convert("RGBA")
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(bytes(source))
    try:
        im = Image.open(source)
    except Image.DecompressionBombError as exc:  # noqa: PERF203
        raise ImageTooLargeError(str(exc)) from exc
    _check_pixels(im.size)                         # по заголовку, до .load()
    try:
        im.load()
    except Image.DecompressionBombError as exc:
        raise ImageTooLargeError(str(exc)) from exc
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    return im


def _check_pixels(size) -> None:
    w, h = size
    if w * h > MAX_IMAGE_PIXELS:
        mp = MAX_IMAGE_PIXELS / 1_000_000
        raise ImageTooLargeError(
            f"Изображение {w}×{h} превышает лимит {mp:.0f} мегапикселей.")


def to_png_bytes(im: Image.Image, optimize: bool = False) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=optimize)
    return buf.getvalue()


def to_data_url(im: Image.Image, fmt: str = "PNG") -> str:
    """PNG-картинка как data: URL — для отдачи в браузер без отдельного запроса."""
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    mime = "image/png" if fmt.upper() == "PNG" else f"image/{fmt.lower()}"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def downscale_for_analysis(im: Image.Image, limit: int = ANALYZE_MAX) -> Image.Image:
    """Уменьшить большое изображение для быстрого анализа фона (без потери для экспорта)."""
    w, h = im.size
    m = max(w, h)
    if m <= limit:
        return im
    s = limit / m
    return im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)


# --- сохранение в разные форматы ------------------------------------------

def save_png(im: Image.Image, path: Path) -> Path:
    im.save(path, format="PNG")
    return path


def save_webp(im: Image.Image, path: Path) -> Path:
    im.save(path, format="WEBP", lossless=True, quality=100)
    return path


def save_ico(im: Image.Image, path: Path, sizes: list[int] | None = None) -> Path:
    """Мультиразмерный .ico (Windows). Источник масштабируем по большему доступному размеру."""
    sizes = [s for s in (sizes or ICO_SIZES) if s <= 256]
    if not sizes:
        sizes = [256]
    base = _square(im, max(sizes))
    base.save(path, format="ICO", sizes=[(s, s) for s in sorted(set(sizes))])
    return path


def save_icns(im: Image.Image, path: Path, sizes: list[int] | None = None) -> Path:
    """.icns для macOS. Pillow требует квадратное изображение; даёт несколько вложенных размеров."""
    sizes = sorted({s for s in (sizes or ICNS_SIZES) if 16 <= s <= 1024})
    base = _square(im, max(sizes))
    base.save(path, format="ICNS", sizes=[(s, s) for s in sizes])
    return path


def save_svg_wrap(im: Image.Image, path: Path) -> Path:
    """Обёртка: PNG, встроенный в SVG-контейнер (удобно вставлять в верстку)."""
    w, h = im.size
    b64 = base64.b64encode(to_png_bytes(im)).decode("ascii")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">\n'
        f'  <image width="{w}" height="{h}" '
        f'xlink:href="data:image/png;base64,{b64}" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink"/>\n'
        f"</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")
    return path


def _square(im: Image.Image, size: int, resample=Image.LANCZOS) -> Image.Image:
    """Вписать в квадрат size×size с прозрачным паддингом (без искажений)."""
    src = im
    w, h = src.size
    if w != h:
        side = max(w, h)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(src, ((side - w) // 2, (side - h) // 2), src)
        src = canvas
    if src.size != (size, size):
        src = src.resize((size, size), resample)
    return src
