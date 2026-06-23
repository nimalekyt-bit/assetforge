"""Генераторы синтетических тестовых картинок (без внешних файлов).

Каждая фикстура возвращает PIL.Image (RGBA или RGB) с известным «правильным»
содержимым, чтобы тесты проверяли движок по МЕТРИКАМ (bbox, alpha coverage,
прозрачность краёв), а не пиксель-в-пиксель.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

W = H = 256
SS = 4  # суперсэмплинг: рисуем в 4× и уменьшаем → сглаженные (антиалиасные) края


def _render(bg, blobs, mode="RGBA") -> Image.Image:
    """Нарисовать эллипсы в большом разрешении и уменьшить — даёт мягкий край.

    blobs: список (box, fill). box задаётся в координатах финального 256×256.
    """
    im = Image.new(mode, (W * SS, H * SS), bg)
    d = ImageDraw.Draw(im)
    for box, fill in blobs:
        d.ellipse([c * SS for c in box], fill=fill)
    return im.resize((W, H), Image.LANCZOS).convert("RGBA")


def transparent_png() -> Image.Image:
    """Объект на полностью прозрачном фоне (alpha уже есть)."""
    return _render((0, 0, 0, 0), [((80, 70, 180, 190), (220, 60, 60, 255))])


def white_bg() -> Image.Image:
    """Объект на белом непрозрачном фоне."""
    return _render((255, 255, 255, 255), [((70, 60, 190, 200), (40, 90, 200, 255))], mode="RGB")


def green_chroma() -> Image.Image:
    """Объект на зелёном хромакее. Суперсэмплинг создаёт зелёную кайму по краю (despill-тест)."""
    return _render((0, 177, 64, 255), [((60, 60, 200, 200), (230, 200, 50, 255))])


def blue_chroma() -> Image.Image:
    """Объект на синем хромакее."""
    return _render((0, 71, 187, 255), [((60, 60, 200, 200), (240, 180, 60, 255))])


def noisy_alpha() -> Image.Image:
    """Объект + редкий полупрозрачный «мусор» по всему кадру (alpha 1..12)."""
    im = transparent_png()
    arr = np.asarray(im).copy()
    rng = np.random.default_rng(42)
    noise = rng.integers(0, 13, size=(H, W)).astype(np.uint8)
    mask = arr[:, :, 3] == 0          # только там, где сейчас пусто
    arr[:, :, 3] = np.where(mask, noise, arr[:, :, 3])
    return Image.fromarray(arr, "RGBA")


def multi_object() -> Image.Image:
    """Два разнесённых объекта (как вордмарк + эмблема)."""
    return _render((0, 0, 0, 0), [
        ((20, 20, 110, 90), (200, 80, 80, 255)),       # верхний-левый
        ((150, 160, 235, 235), (80, 160, 220, 255)),   # нижний-правый
    ])


def tiny_logo() -> Image.Image:
    """Очень маленький объект в большом прозрачном кадре."""
    return _render((0, 0, 0, 0), [((120, 120, 136, 136), (240, 240, 240, 255))])


ALL = {
    "transparent": transparent_png,
    "white": white_bg,
    "green": green_chroma,
    "blue": blue_chroma,
    "noisy": noisy_alpha,
    "multi": multi_object,
    "tiny": tiny_logo,
}
