"""Карта значимости (saliency) и subject-aware центр для умного COVER-кропа.

Зачем: при вписывании несквадратного источника в несквадратную целевую рамку в
режиме COVER нужно решить, КАКОЕ окно вырезать. Тупой центр режет «по геометрии»
и часто отрезает самое важное. Здесь считается лёгкая карта значимости (без
scipy/cv2/сети — только numpy + Pillow) и взвешенный центр значимости, который
:func:`cover_window` ставит в середину вырезаемого окна.

Значимость = нормированная смесь двух сигналов:
  (a) альфа-маска объекта (где вообще есть контент);
  (b) |градиент| яркости (Sobel) — края и детали важнее плоских заливок.
После смешивания карта сглаживается и нормируется. Вычитание базового уровня
(минимума) убирает «пьедестал» сплошных областей, поэтому центр тянется к
деталям субъекта, а не к геометрической середине однотонной заливки.

Скорость: для расчёта картинка ужимается до ~512px по большей стороне. Центр
возвращается в НОРМИРОВАННЫХ координатах [0..1], поэтому масштаб расчёта на
результат не влияет.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

try:  # пакетный импорт (python -m / import assetforge...)
    from .detect import content_bbox
except ImportError:  # прямой запуск файла как скрипта
    from assetforge.core.detect import content_bbox

# сторона, до которой ужимаем источник для расчёта saliency (скорость)
ANALYZE_SIDE = 512
# веса смеси: градиент важнее альфы («края/детали важнее плоских заливок»)
ALPHA_W = 0.4
GRAD_W = 0.6
# коэффициенты яркости Rec.601
_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)
_EPS = 1e-8


def saliency_map(im: Image.Image) -> np.ndarray:
    """Карта значимости как float32 H×W в диапазоне 0..1 (под размер изображения).

    Расчёт идёт на уменьшенной копии (ANALYZE_SIDE), затем карта растягивается
    обратно до размера ``im`` билинейно. 0 — фон/плоская заливка, 1 — самые
    значимые края/детали субъекта.
    """
    small, (ow, oh) = _saliency_small(im)
    sh, sw = small.shape
    if (sw, sh) == (ow, oh):
        return small
    up = Image.fromarray(small, mode="F").resize((ow, oh), Image.BILINEAR)
    return np.asarray(up, dtype=np.float32)


def saliency_center(im: Image.Image) -> tuple[float, float]:
    """Нормированный центр значимости ``(cx, cy)`` в [0..1] — взвешенный центроид.

    Фолбэк (объект однороден/пуст, значимость вырождена): центр content_bbox,
    а если контента нет вовсе — геометрический центр ``(0.5, 0.5)``. Никогда не
    падает на пустых / 1×1 / равномерных картинках.
    """
    small, _ = _saliency_small(im)
    total = float(small.sum())
    if total <= _EPS:                      # пусто / однородная заливка -> вырождено
        return _bbox_center(im)

    sh, sw = small.shape
    xs = (np.arange(sw, dtype=np.float32) + 0.5) / sw   # нормир. координаты центров пикселей
    ys = (np.arange(sh, dtype=np.float32) + 0.5) / sh
    cx = float((small.sum(axis=0) * xs).sum() / total)
    cy = float((small.sum(axis=1) * ys).sum() / total)
    if not (np.isfinite(cx) and np.isfinite(cy)):
        return _bbox_center(im)
    return _clamp01(cx), _clamp01(cy)


def cover_window(bw: int, bh: int, tw: int, th: int,
                 center: tuple[float, float]) -> tuple[int, int, int, int]:
    """Окно для умного COVER-кропа в координатах МАСШТАБИРОВАННОГО изображения.

    Источник ``bw×bh`` масштабируется коэффициентом ``max(tw/bw, th/bh)`` так,
    чтобы целиком покрыть рамку ``tw×th``; из получившегося изображения вырезается
    окно ``tw×th``, спозиционированное так, чтобы нормированный ``center`` попал в
    его середину (с клампом к границам). Возвращает ``(left, top, right, bottom)``.
    """
    bw, bh, tw, th = int(bw), int(bh), int(tw), int(th)
    if bw <= 0 or bh <= 0 or tw <= 0 or th <= 0:      # вырожденный ввод — без падения
        return (0, 0, max(0, tw), max(0, th))

    scale = max(tw / bw, th / bh)
    sw = max(tw, int(round(bw * scale)))              # масштаб = max(...) гарантирует sw>=tw, sh>=th
    sh = max(th, int(round(bh * scale)))

    cx = _clamp01(float(center[0])) * sw              # центр значимости в координатах масштаб. картинки
    cy = _clamp01(float(center[1])) * sh
    left = min(max(0, int(round(cx - tw / 2))), sw - tw)
    top = min(max(0, int(round(cy - th / 2))), sh - th)
    return (left, top, left + tw, top + th)


# --- внутреннее ------------------------------------------------------------

def _saliency_small(im: Image.Image) -> tuple[np.ndarray, tuple[int, int]]:
    """Saliency на уменьшенной копии. Возвращает (карта float32 0..1, (orig_w, orig_h))."""
    rgba = im if im.mode == "RGBA" else im.convert("RGBA")
    ow, oh = rgba.size
    m = max(ow, oh)
    if m > ANALYZE_SIDE:
        s = ANALYZE_SIDE / m
        small = rgba.resize((max(1, round(ow * s)), max(1, round(oh * s))), Image.LANCZOS)
    else:
        small = rgba
    arr = np.asarray(small, dtype=np.float32)
    if arr.ndim == 2:                                  # на всякий случай (grayscale)
        arr = np.dstack([arr, arr, arr, np.full_like(arr, 255)])

    alpha = arr[:, :, 3] / 255.0
    luma = (arr[:, :, :3] @ _LUMA) / 255.0
    # премультипликация яркости альфой: убирает «мусорный» RGB в прозрачных зонах
    # и заодно даёт градиент на самой кромке объекта (граница alpha)
    lp = luma * alpha

    grad = _sobel_mag(lp)
    gmax = float(grad.max())
    if gmax > _EPS:
        grad = grad / gmax

    sal = ALPHA_W * alpha + GRAD_W * grad
    r = max(1, round(max(sal.shape) * 0.02))
    sal = _box_blur(sal, r)

    sal = sal - float(sal.min())                       # вычесть пьедестал плоских областей
    smax = float(sal.max())
    if smax > _EPS:
        sal = sal / smax
    else:
        sal = np.zeros_like(sal)                       # равномерная заливка -> всё 0 (фолбэк по центру)
    return sal.astype(np.float32), (ow, oh)


def _sobel_mag(a: np.ndarray) -> np.ndarray:
    """Модуль градиента яркости (Sobel) на numpy; края дополняются репликацией
    (на однородном поле и на границах кадра градиент строго 0)."""
    p = np.pad(a, 1, mode="edge")
    gx = ((p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:])
          - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2]))
    gy = ((p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:])
          - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:]))
    return np.sqrt(gx * gx + gy * gy)


def _box_blur(a: np.ndarray, r: int) -> np.ndarray:
    """Быстрое box-сглаживание (integral image, O(N)); окно (2r+1) с клампом к краям."""
    if r < 1:
        return a.astype(np.float32)
    h, w = a.shape
    ii = np.zeros((h + 1, w + 1), dtype=np.float64)
    ii[1:, 1:] = np.cumsum(np.cumsum(a.astype(np.float64), axis=0), axis=1)
    y = np.arange(h)
    x = np.arange(w)
    y0 = np.clip(y - r, 0, h)[:, None]
    y1 = np.clip(y + r + 1, 0, h)[:, None]
    x0 = np.clip(x - r, 0, w)[None, :]
    x1 = np.clip(x + r + 1, 0, w)[None, :]
    s = ii[y1, x1] - ii[y0, x1] - ii[y1, x0] + ii[y0, x0]
    cnt = (y1 - y0) * (x1 - x0)
    return (s / cnt).astype(np.float32)


def _bbox_center(im: Image.Image) -> tuple[float, float]:
    """Нормированный центр content_bbox; (0.5, 0.5) если контента нет."""
    bb = content_bbox(im)
    if bb is None:
        return 0.5, 0.5
    w, h = im.size
    if w <= 0 or h <= 0:
        return 0.5, 0.5
    x0, y0, x1, y1 = bb
    return _clamp01((x0 + x1) / 2 / w), _clamp01((y0 + y1) / 2 / h)


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else float(v)


# --- self-test -------------------------------------------------------------

if __name__ == "__main__":
    from PIL import ImageDraw

    def _offset_blob() -> Image.Image:
        """Объект, смещённый в левый-верхний угол (центр ~0.3, 0.3)."""
        im = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([70, 70, 170, 170], fill=(230, 70, 70, 255))   # центр (120,120) = (0.3,0.3)
        return im

    def _uniform_fill() -> Image.Image:
        """Равномерная непрозрачная заливка (значимости нет -> центр 0.5, 0.5)."""
        return Image.new("RGBA", (300, 300), (180, 180, 180, 255))

    def _empty() -> Image.Image:
        return Image.new("RGBA", (64, 64), (0, 0, 0, 0))

    print("saliency_map(im)                         -> np.ndarray float32 HxW, 0..1")
    print("saliency_center(im)                      -> (cx, cy) in [0..1]")
    print("cover_window(bw,bh,tw,th,center)         -> (left, top, right, bottom)")
    print("-" * 64)

    off = _offset_blob()
    smap = saliency_map(off)
    cx, cy = saliency_center(off)
    print(f"offset blob:   center=({cx:.3f}, {cy:.3f})  ожидаем ~(0.30, 0.30)  "
          f"map={smap.shape} {smap.dtype} [{smap.min():.2f}..{smap.max():.2f}]")
    ok_off = abs(cx - 0.3) < 0.08 and abs(cy - 0.3) < 0.08

    ux, uy = saliency_center(_uniform_fill())
    print(f"uniform fill:  center=({ux:.3f}, {uy:.3f})  ожидаем (0.50, 0.50)")
    ok_uni = abs(ux - 0.5) < 1e-6 and abs(uy - 0.5) < 1e-6

    ex, ey = saliency_center(_empty())
    print(f"empty canvas:  center=({ex:.3f}, {ey:.3f})  ожидаем (0.50, 0.50)")
    ok_empty = (ex, ey) == (0.5, 0.5)

    # cover_window: источник 1000x1000, рамка 800x400 (широкая), центр субъекта (0.3,0.3)
    win = cover_window(1000, 1000, 800, 400, (cx, cy))
    w_w, w_h = win[2] - win[0], win[3] - win[1]
    print(f"cover_window:  {win}  size={w_w}x{w_h}  ожидаем 800x400 в пределах кадра")
    ok_win = (w_w, w_h) == (800, 400) and win[0] >= 0 and win[1] >= 0

    print("-" * 64)
    all_ok = ok_off and ok_uni and ok_empty and ok_win
    print("SELF-TEST:", "OK" if all_ok else "FAIL",
          dict(offset=ok_off, uniform=ok_uni, empty=ok_empty, window=ok_win))
    import sys
    sys.exit(0 if all_ok else 1)
