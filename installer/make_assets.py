"""Генерация фирменной графики установщика AssetForge из бренд-палитры «кузницы».

Создаёт:
  installer/AssetForge.ico   — иконка приложения/exe (мультиразмерная)
  installer/logo.png         — логотип-искра на угле (для окон установки/сплэша)

Палитра (из web/style.css): уголь #0b0907, угли #ff6a1a/#ff3f0d, латунь #f0cd8f.
Запуск:  python installer/make_assets.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent

COAL = (11, 9, 7, 255)          # #0b0907
EMBER_TOP = (255, 241, 223)     # #fff1df
EMBER_MID = (240, 205, 143)     # #f0cd8f
EMBER_BOT = (255, 63, 13)       # #ff3f0d


def _spark_path(cx: float, cy: float, r_out: float, r_in: float) -> list[tuple[float, float]]:
    """4-конечная искра-звезда (как в favicon): длинные верт/гор лучи."""
    # точки: верх, (внутр) право-верх, право, ... — 8 точек (4 острых + 4 впадины)
    pts = []
    # порядок углов: 90 (верх), 45, 0, -45 ... по кругу
    spikes = [(-90, r_out), (-45, r_in), (0, r_out), (45, r_in),
              (90, r_out), (135, r_in), (180, r_out), (-135, r_in)]
    # вытянем вертикаль: верх/низ длиннее
    for ang, r in spikes:
        rr = r
        if ang in (-90, 90):
            rr = r_out * 1.18
        a = math.radians(ang)
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def _ember_gradient(size: int) -> Image.Image:
    """Вертикальный градиент углей: светлый верх → латунь → раскалённый низ."""
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = grad.load()
    for y in range(size):
        t = y / max(1, size - 1)
        if t < 0.45:
            k = t / 0.45
            c = _lerp(EMBER_TOP, EMBER_MID, k)
        else:
            k = (t - 0.45) / 0.55
            c = _lerp(EMBER_MID, EMBER_BOT, k)
        for x in range(size):
            px[x, y] = (c[0], c[1], c[2], 255)
    return grad


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def render_icon(size: int = 512) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # фон: скруглённый угольный квадрат
    radius = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=COAL)
    # лёгкое раскалённое свечение снизу
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([size * 0.1, size * 0.55, size * 0.9, size * 1.15],
               fill=(255, 90, 20, 70))
    img.alpha_composite(glow)

    # искра с градиентной заливкой (через маску)
    cx = cy = size / 2
    pts = _spark_path(cx, cy, size * 0.40, size * 0.155)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    grad = _ember_gradient(size)
    img.paste(grad, (0, 0), mask)
    return img


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    base = render_icon(512)
    # PNG-логотип (для окон установки)
    base.save(HERE / "logo.png")
    # мультиразмерный ICO
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [base.resize((s, s), Image.LANCZOS) for s in ico_sizes]
    frames[-1].save(HERE / "AssetForge.ico", format="ICO",
                    sizes=[(s, s) for s in ico_sizes], append_images=frames[:-1])
    print("written:", HERE / "AssetForge.ico", "and logo.png")


if __name__ == "__main__":
    main()
