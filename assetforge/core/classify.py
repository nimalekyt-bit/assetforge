"""Авто-классификатор типа ассета (Tier 1 «умность»).

Чистая эвристика на numpy + Pillow — БЕЗ сети и тяжёлых зависимостей. По уже
очищенной от фона RGBA-картинке пытается угадать, *что* это за ассет
(иконка / лого / вордмарк / фото / иллюстрация / спрайт-лист) и какой пресет
разумнее предложить пользователю.

Сигналы (все считаются локально, пороги вынесены в константы ниже):

* **соотношение сторон** content-bbox — широкое → вордмарк, около-квадрат → иконка;
* **число объектов** (от :func:`detect.split_objects`) — много похожих по размеру в
  несколько рядов → спрайт-лист;
* **число уникальных цветов** (адаптивная палитра, как просили — ``convert('P',
  ADAPTIVE, 256).getcolors()``) — мало → «векторное» (лого/иконка), много → фото;
* **«плоскость»** (доля пикселей, равных соседу) — высокая → резкие заливки
  (вектор), низкая → плавные градиенты (фото/растр);
* **полупрозрачность** (доля частично-прозрачных пикселей) — мягкие края/стекло;
* **разрешение** источника — мелкий → предупреждение про мыло при апскейле.

Функция устойчива к краевым случаям (пустой холст, 1 объект, огромная картинка)
и на нормальных входах не бросает исключений.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

try:  # обычный импорт как часть пакета
    from .detect import content_bbox, split_objects
except ImportError:  # запуск файла напрямую: python assetforge/core/classify.py
    from assetforge.core.detect import content_bbox, split_objects


# --- пороги (документированы) ----------------------------------------------

ALPHA_THRESHOLD = 16        # выше этого alpha считаем «контентом»
WORK_MAX_SIDE = 384         # рабочая копия ужимается до этой стороны (NEAREST, быстро)

ASPECT_WORDMARK = 2.2       # шире этого (W/H) по content-bbox → вордмарк
ASPECT_ICON_LO = 0.8        # диапазон «около-квадрат» → кандидат в иконку
ASPECT_ICON_HI = 1.25

SPRITE_MIN_OBJECTS = 4      # > 3 объектов — возможный спрайт-лист
SPRITE_MAX_CV = 0.45        # коэф. вариации размеров объектов ниже → «похожего размера»
SPRITE_MIN_ROWS = 2         # требуем 2D-раскладку (≥2 ряда), чтобы не путать с вордмарком

FEW_COLORS = 48             # < этого уникальных цветов → «векторное» (лого/иконка)
MANY_COLORS = 160           # > этого + плавные переходы → фото
FLAT_EPS = 6                # |Δцвета| с соседом ≤ этого считаем «плоским» пикселем
FLAT_VECTOR = 0.55          # доля плоских пикселей выше → резкие заливки (вектор)
FLAT_PHOTO = 0.25           # доля плоских пикселей ниже → плавные градиенты (фото)

PARTIAL_ALPHA_SOFT = 0.20   # доля полупрозрачных пикселей выше → мягкие края/прозрачность
SMALL_SOURCE = 128          # сторона контента меньше → риск мыла при апскейле

SENTINEL = (255, 0, 255)    # чем заливаем прозрачные пиксели перед подсчётом цветов


# --- таблица соответствия тип → пресет -------------------------------------

KIND_TO_PRESET: dict[str, str] = {
    "icon": "icon-set",
    "logo": "web-logo",
    "wordmark": "web-logo",
    "sprite-sheet": "icon-set",
    "photo": "all",           # фото для иконок не идеально → универсальный набор
    "illustration": "icon-set",
}


def preset_for_kind(kind: str) -> str:
    """Разумный пресет по типу ассета (всегда существующее имя пресета)."""
    return KIND_TO_PRESET.get(kind, "icon-set")


# --- основной API ----------------------------------------------------------

def classify_asset(image, objects=None, bg_mode=None) -> dict:
    """Угадать тип ассета и предложить пресет.

    :param image: PIL.Image (желательно RGBA, уже после удаления фона).
    :param objects: список bbox ``(l, t, r, b)`` от :func:`detect.split_objects`;
        ``None`` → посчитаем сами.
    :param bg_mode: строка режима фона (``auto``/``white``/``chroma``/…), опционально.
    :returns: ``{"kind", "suggested_preset", "confidence", "reasons"}``.
    """
    img = image.convert("RGBA") if image.mode != "RGBA" else image

    reasons: list[str] = []
    if bg_mode:
        reasons.append(f"режим удаления фона: {bg_mode}")

    bbox = content_bbox(img, ALPHA_THRESHOLD)
    if bbox is None:
        # пустой/полностью прозрачный холст — не гадаем, отдаём безопасный дефолт
        reasons.append("контент не найден (холст пустой) → базовый набор иконок")
        return _result("icon", 0.2, reasons)

    if objects is None:
        objects = split_objects(img, threshold=ALPHA_THRESHOLD, mode="objects")
    objects = list(objects or [])
    if not objects:                       # на всякий: bbox есть, а компонент нет
        objects = [bbox]

    cx0, cy0, cx1, cy1 = bbox
    cw, ch = cx1 - cx0, cy1 - cy0
    aspect = cw / ch if ch else 1.0

    feats = _features(img, bbox)
    n_colors = feats["n_colors"]
    flat_frac = feats["flat_frac"]
    partial = feats["partial_frac"]

    stats = _object_stats(objects)

    if min(cw, ch) < SMALL_SOURCE:
        reasons.append(f"мелкий контент {cw}×{ch}px → при апскейле возможна мыльность")
    if partial >= PARTIAL_ALPHA_SOFT:
        reasons.append(f"полупрозрачных пикселей {partial:.0%} → мягкие края/прозрачность")

    # 1) Спрайт-лист: много объектов похожего размера, разложенных в ≥2 ряда.
    #    (Один горизонтальный ряд намеренно НЕ считаем спрайтом — это чаще вордмарк.)
    if (stats["n"] >= SPRITE_MIN_OBJECTS and stats["uniform"]
            and stats["rows"] >= SPRITE_MIN_ROWS):
        reasons.insert(
            0, f"объектов {stats['n']} похожего размера в {stats['rows']} ряда "
               f"→ спрайт-лист (нарежу по объектам)")
        conf = _clamp(0.55 + 0.35 * (1.0 - min(1.0, stats["cv"])))
        return _result("sprite-sheet", conf, reasons)

    # 2) Вордмарк: явно широкий content-bbox.
    if aspect > ASPECT_WORDMARK:
        reasons.insert(0, f"соотношение сторон {aspect:.2f}:1 (>{ASPECT_WORDMARK}) "
                          f"→ широкое лого/вордмарк")
        conf = _clamp(0.55 + 0.12 * (aspect - ASPECT_WORDMARK))
        return _result("wordmark", conf, reasons)

    near_square = ASPECT_ICON_LO <= aspect <= ASPECT_ICON_HI
    vector_like = n_colors <= FEW_COLORS and flat_frac >= FLAT_VECTOR
    photo_like = n_colors >= MANY_COLORS and flat_frac <= FLAT_PHOTO

    # 3) Фото: много цветов и плавные переходы.
    if photo_like:
        reasons.insert(0, f"цветов ~{n_colors} (много) и плавные переходы "
                          f"(плоских {flat_frac:.0%}) → похоже на фотографию")
        reasons.append("фото для иконок не идеально — предложен универсальный набор «all»")
        conf = _clamp(0.55 + 0.3 * (1.0 - flat_frac)
                      + min(0.1, (n_colors - MANY_COLORS) * 0.001))
        return _result("photo", conf, reasons)

    # 4) Векторное (мало цветов + резкие заливки) → иконка (квадрат) или лого.
    if vector_like:
        if near_square:
            reasons.insert(0, f"около-квадрат {aspect:.2f}:1, цветов ~{n_colors} (мало), "
                              f"резкие края (плоских {flat_frac:.0%}) → иконка")
            conf = _clamp(0.6 + 0.25 * flat_frac + (0.1 if n_colors <= 16 else 0.0))
            return _result("icon", conf, reasons)
        reasons.insert(0, f"цветов ~{n_colors} (мало), резкие края "
                          f"(плоских {flat_frac:.0%}), форма {aspect:.2f}:1 → лого")
        conf = _clamp(0.55 + 0.2 * flat_frac)
        return _result("logo", conf, reasons)

    # 5) Промежуточный случай: умеренно много цветов / лёгкие градиенты, но не фото.
    if near_square:
        reasons.insert(0, f"цветов ~{n_colors}, плоских {flat_frac:.0%}, около-квадрат "
                          f"{aspect:.2f}:1 → иллюстрация (можно нарезать в иконки)")
        conf = _clamp(0.5 + 0.15 * flat_frac)
        return _result("illustration", conf, reasons)

    reasons.insert(0, f"цветов ~{n_colors}, плоских {flat_frac:.0%}, форма {aspect:.2f}:1 "
                      f"→ лого (нестандартная пропорция)")
    conf = _clamp(0.5 + 0.15 * flat_frac)
    return _result("logo", conf, reasons)


# --- внутреннее ------------------------------------------------------------

def _result(kind: str, confidence: float, reasons: list[str]) -> dict:
    return {
        "kind": kind,
        "suggested_preset": preset_for_kind(kind),
        "confidence": round(float(confidence), 2),
        "reasons": reasons,
    }


def _clamp(x: float, lo: float = 0.05, hi: float = 0.97) -> float:
    return max(lo, min(hi, x))


def _features(img: Image.Image, bbox) -> dict:
    """Цвета / «плоскость» / полупрозрачность по контенту внутри bbox.

    Считаем на уменьшенной (NEAREST — сохраняет резкие края и плоские заливки)
    рабочей копии, ограниченной bbox контента. Прозрачные пиксели заливаются
    sentinel-цветом, чтобы «мусорный» RGB под alpha=0 не раздувал число цветов.
    """
    crop = img.crop(bbox)
    w, h = crop.size
    scale = min(1.0, WORK_MAX_SIDE / max(w, h)) if max(w, h) else 1.0
    if scale < 1.0:
        crop = crop.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                           Image.NEAREST)

    arr = np.asarray(crop, dtype=np.uint8)
    if arr.ndim != 3 or arr.shape[2] < 4:        # подстраховка от не-RGBA
        crop = crop.convert("RGBA")
        arr = np.asarray(crop, dtype=np.uint8)

    alpha = arr[:, :, 3]
    solid = alpha > ALPHA_THRESHOLD
    content_px = int(solid.sum())

    # полупрозрачность
    partial_px = int((solid & (alpha < 240)).sum())
    partial_frac = partial_px / content_px if content_px else 0.0

    # число уникальных цветов (адаптивная палитра по контенту)
    rgb = arr[:, :, :3].copy()
    has_transparent = bool((~solid).any())
    if has_transparent:
        rgb[~solid] = SENTINEL
    n_colors = _count_colors(Image.fromarray(rgb, "RGB"))
    if has_transparent:
        n_colors = max(1, n_colors - 1)          # минус sentinel-цвет

    # «плоскость»: доля соседних пар внутри контента с почти равным цветом
    rgb_i = arr[:, :, :3].astype(np.int16)
    flat_num = flat_den = 0
    if rgb_i.shape[1] > 1:
        vr = solid[:, :-1] & solid[:, 1:]
        dr = np.abs(rgb_i[:, :-1, :] - rgb_i[:, 1:, :]).max(axis=2)
        flat_num += int((vr & (dr <= FLAT_EPS)).sum()); flat_den += int(vr.sum())
    if rgb_i.shape[0] > 1:
        vd = solid[:-1, :] & solid[1:, :]
        dd = np.abs(rgb_i[:-1, :, :] - rgb_i[1:, :, :]).max(axis=2)
        flat_num += int((vd & (dd <= FLAT_EPS)).sum()); flat_den += int(vd.sum())
    flat_frac = flat_num / flat_den if flat_den else 1.0

    return {"n_colors": int(n_colors), "flat_frac": float(flat_frac),
            "partial_frac": float(partial_frac)}


def _count_colors(rgb_img: Image.Image, max_colors: int = 256) -> int:
    """Число уникальных цветов через адаптивную палитру (как просили)."""
    try:
        pal = rgb_img.convert("P", palette=Image.ADAPTIVE, colors=max_colors)
        cols = pal.getcolors(max_colors)
        return len(cols) if cols else max_colors
    except (ValueError, OSError):
        return max_colors


def _object_stats(objects) -> dict:
    """Статистика по объектам: число, однородность размеров, число рядов."""
    n = len(objects)
    if n == 0:
        return {"n": 0, "cv": 1.0, "uniform": False, "rows": 0, "mean_aspect": 1.0}

    sides, aspects, tops, heights = [], [], [], []
    for b in objects:
        x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
        bw = max(1, x1 - x0); bh = max(1, y1 - y0)
        sides.append(max(bw, bh)); aspects.append(bw / bh)
        tops.append(y0); heights.append(bh)

    mean_s = sum(sides) / n
    cv = (sum((s - mean_s) ** 2 for s in sides) / n) ** 0.5 / mean_s if mean_s else 1.0
    mean_aspect = sum(aspects) / n

    # число рядов: группируем верхние границы с допуском ~0.6 медианной высоты
    med_h = sorted(heights)[n // 2]
    tol = max(4, med_h * 0.6)
    row_refs: list[float] = []
    for t in sorted(tops):
        if not any(abs(t - r) <= tol for r in row_refs):
            row_refs.append(t)

    return {"n": n, "cv": float(cv), "uniform": cv < SPRITE_MAX_CV,
            "rows": len(row_refs), "mean_aspect": float(mean_aspect)}


# --- self-тест -------------------------------------------------------------

if __name__ == "__main__":
    from PIL import ImageDraw

    def _icon() -> Image.Image:
        im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((40, 40, 216, 216), fill=(40, 120, 220, 255))
        d.rectangle((96, 96, 160, 160), fill=(255, 255, 255, 255))
        return im

    def _wordmark() -> Image.Image:
        im = Image.new("RGBA", (820, 180), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for i in range(5):                       # 5 «букв» в один ряд
            x = 40 + i * 150
            d.rectangle((x, 50, x + 90, 150), fill=(30, 30, 30, 255))
        return im

    def _photo() -> Image.Image:
        rng = np.random.default_rng(7)
        yy, xx = np.mgrid[0:300, 0:300]
        r = (xx * 0.7).astype(np.int16)
        g = (yy * 0.7).astype(np.int16)
        b = ((xx + yy) * 0.4).astype(np.int16)
        rgb = np.stack([r, g, b], axis=2)
        rgb = (rgb + rng.integers(0, 60, size=rgb.shape)) % 256   # шум > FLAT_EPS
        arr = np.dstack([rgb.astype(np.uint8),
                         np.full((300, 300), 255, np.uint8)])
        return Image.fromarray(arr, "RGBA")

    samples = [("иконка", _icon()), ("вордмарк", _wordmark()), ("фото", _photo())]
    for title, sample in samples:
        res = classify_asset(sample)
        print(f"[{title}] size={sample.size}")
        print(f"   kind={res['kind']!r}  preset={res['suggested_preset']!r}  "
              f"confidence={res['confidence']}")
        for r in res["reasons"]:
            print(f"     - {r}")
        print()
