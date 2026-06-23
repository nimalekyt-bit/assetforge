"""Детект типа фона и его удаление.

Режимы (``BackgroundConfig.mode``):
  - ``none``   — ничего не делаем;
  - ``alpha``  — у картинки уже есть прозрачность, просто нормализуем;
  - ``white``  — однотонный светлый фон;
  - ``solid``  — любой однотонный фон (цвет берём из рамки или ``key_color``);
  - ``chroma`` — зелёный/синий хромакей (color-key + despill);
  - ``ai``     — нейросеть rembg/u2net (опционально, если установлена);
  - ``auto``   — определить тип автоматически и выбрать из перечисленного.

Возвращаем всегда RGBA с мягким (антиалиасным) краем — без «лесенки».
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from PIL import Image

from .config import BackgroundConfig


@dataclass
class BackgroundResult:
    image: Image.Image          # RGBA после удаления фона
    detected_mode: str          # какой режим реально применили
    key_color: tuple[int, int, int] | None
    notes: list[str]            # человекочитаемые заметки (для UI/QA)


# --- публичная точка входа -------------------------------------------------

def remove_background(im: Image.Image, cfg: BackgroundConfig) -> BackgroundResult:
    im = im.convert("RGBA")
    arr = np.asarray(im).astype(np.float32)
    notes: list[str] = []

    mode = cfg.mode or "auto"
    if mode == "auto":
        mode, info = detect_background(arr)
        notes.append(f"auto → {mode} ({info})")

    if mode == "none":
        return BackgroundResult(im, "none", None, notes)

    if mode == "ai":
        out, ai_notes = _remove_ai(im)
        notes.extend(ai_notes)
        return BackgroundResult(out, "ai", None, notes)

    if mode == "alpha":
        out = _clean_existing_alpha(arr)
        return BackgroundResult(_to_img(out), "alpha", None, notes)

    # шумо-адаптивный порог: расширяем tolerance на разброс цвета рамки. Источник мог
    # пройти через JPEG (фон-шахматка «рассыпана» в десятки оттенков) — иначе шумные
    # пиксели фона не попадают в порог и остаются «оправой»/точками по краю.
    noise = float(_border_pixels(arr)[:, :3].std(axis=0).mean())
    eff = replace(cfg, tolerance=float(cfg.tolerance) + min(40.0, noise * 3.0))

    if mode == "checker":
        keys = _detect_two_tones(arr) or [_resolve_key_color(arr, cfg, "white")]
        out = _color_key(arr, keys, eff, chroma=False)
        notes.append(f"checker keys={[tuple(int(round(c)) for c in k) for k in keys]} tol≈{eff.tolerance:.0f}")
        return BackgroundResult(_to_img(out), "checker",
                                tuple(int(round(c)) for c in keys[0]), notes)

    # white / solid / chroma — все через color-key
    key = _resolve_key_color(arr, cfg, mode)
    out = _color_key(arr, [key], eff, chroma=(mode == "chroma"))
    notes.append(f"key={key} tol≈{eff.tolerance:.0f} soft={cfg.softness}")
    return BackgroundResult(_to_img(out), mode, key, notes)


# --- авто-детект -----------------------------------------------------------

def detect_background(arr: np.ndarray) -> tuple[str, str]:
    """Определить тип фона по рамке изображения. Возвращает (mode, описание).

    Статистику фона считаем только по непрозрачным пикселям. Если контента не
    осталось (кадр пуст/прозрачен) или фон неотличим от объекта (вся картинка
    одноцветная) — откатываемся к ``none``, чтобы не «выесть» контент молча.
    """
    h, w = arr.shape[:2]
    alpha = arr[:, :, 3]

    # 0) кадр пуст/прозрачен — нечего обрабатывать
    opaque_mask = alpha > 16
    if not bool(opaque_mask.any()):
        return "none", "Кадр пуст/прозрачен"

    # 1) уже есть значимая прозрачность?
    transparent_frac = float((alpha < 250).mean())
    if transparent_frac > 0.05 and float((alpha < 16).mean()) > 0.02:
        return "alpha", f"{transparent_frac:.0%} полупрозрачных пикселей"

    # 2) собрать пиксели рамки (по непрозрачным)
    border = _border_pixels(arr)
    rgb = border[:, :3]
    mean = rgb.mean(axis=0)
    std = rgb.std(axis=0)
    uniform = float(std.mean())

    # 2a) одноцветная картинка: весь непрозрачный контент совпадает с цветом
    # рамки → объект неотличим от фона. Удаление бы «выело» весь кадр.
    content_rgb = arr[:, :, :3][opaque_mask]
    far = np.sqrt(((content_rgb - mean) ** 2).sum(axis=1)) > 24.0
    if float(far.mean()) < 0.005:
        return "none", "Фон неотличим от объекта — удаление фона отключено"

    r, g, b = mean
    # 2b) двухтоновый фон / шахматка прозрачности (две дискретные клетки — серые ИЛИ цветные)
    tones = _detect_two_tones(arr)
    if tones:
        t0 = tuple(int(round(c)) for c in tones[0]); t1 = tuple(int(round(c)) for c in tones[1])
        return "checker", f"двухтоновый фон {t0}+{t1}"
    # 3) хромакей: один из каналов доминирует и фон достаточно однороден
    if uniform < 40 and g > r + 25 and g > b + 25:
        return "chroma", f"зелёный фон rgb≈({r:.0f},{g:.0f},{b:.0f})"
    if uniform < 40 and b > r + 25 and b > g + 25:
        return "chroma", f"синий фон rgb≈({r:.0f},{g:.0f},{b:.0f})"

    # 4) однотонный
    if uniform < 18:
        if mean.mean() > 220:
            return "white", f"светлый фон rgb≈({r:.0f},{g:.0f},{b:.0f})"
        return "solid", f"однотонный rgb≈({r:.0f},{g:.0f},{b:.0f})"

    # 5) сложный фон — без AI не трогаем
    return "none", f"неоднородный фон (std≈{uniform:.0f}); нужен AI-режим"


def _border_pixels(arr: np.ndarray, frac: float = 0.06) -> np.ndarray:
    """Пиксели по периметру (рамка шириной frac), только достаточно непрозрачные."""
    h, w = arr.shape[:2]
    bh = max(1, int(h * frac))
    bw = max(1, int(w * frac))
    parts = [
        arr[:bh, :, :].reshape(-1, 4),
        arr[-bh:, :, :].reshape(-1, 4),
        arr[:, :bw, :].reshape(-1, 4),
        arr[:, -bw:, :].reshape(-1, 4),
    ]
    px = np.concatenate(parts, axis=0)
    opaque = px[px[:, 3] > 200]
    return opaque if len(opaque) > 0 else px


def _detect_two_tones(arr: np.ndarray) -> list[tuple[float, float, float]] | None:
    """Распознать ДВУХТОНОВЫЙ фон (шахматка прозрачности любых цветов).

    2-means по пикселям рамки в RGB. Возвращает 2 доминирующих цвета, если фон —
    это две чередующиеся ДИСКРЕТНЫЕ клетки (серые ИЛИ цветные). Отличает шахматку от
    градиента (у градиента кластеры «размазаны») и от однотонного фона. Иначе None.
    """
    border = _border_pixels(arr)[:, :3].astype(np.float32)
    if len(border) < 24:
        return None
    c0, c1 = border.min(axis=0).copy(), border.max(axis=0).copy()   # инициализация крайними
    m0 = None
    for _ in range(10):
        d0 = ((border - c0) ** 2).sum(axis=1)
        d1 = ((border - c1) ** 2).sum(axis=1)
        m0 = d0 <= d1
        if not m0.any() or m0.all():
            return None
        nc0, nc1 = border[m0].mean(axis=0), border[~m0].mean(axis=0)
        if np.allclose(nc0, c0) and np.allclose(nc1, c1):
            break
        c0, c1 = nc0, nc1
    f0 = float(m0.mean())
    if f0 < 0.15 or f0 > 0.85:                    # один тон доминирует → не шахматка
        return None
    sep = float(np.sqrt(((c0 - c1) ** 2).sum()))
    if sep < 25:                                  # тона почти совпадают → однотонный (white/solid)
        return None
    # ДИСКРЕТНОСТЬ: у шахматки каждый тон ПЛОТНЫЙ (разброс внутри кластера ≈ 0), у градиента
    # «клетки» — это половины диапазона, разброс большой. Малое отношение разброс/разделение → шахматка.
    sd0 = float(np.sqrt(((border[m0] - c0) ** 2).sum(axis=1)).mean())
    sd1 = float(np.sqrt(((border[~m0] - c1) ** 2).sum(axis=1)).mean())
    if (sd0 + sd1) / 2.0 > sep * 0.10:            # кластеры размазаны → плавный градиент, не шахматка
        return None
    return [tuple(float(v) for v in c0), tuple(float(v) for v in c1)]


# --- color-key с мягким краем ---------------------------------------------

def _resolve_key_color(arr: np.ndarray, cfg: BackgroundConfig, mode: str) -> tuple[int, int, int]:
    if cfg.key_color:
        # гарантируем ровно 3 компонента (короткий список из UI не должен ломать broadcast)
        kc = (list(cfg.key_color) + [0, 0, 0])[:3]
        return tuple(int(c) for c in kc)
    # ФАКТИЧЕСКИЙ цвет рамки (в т.ч. для white): near-white шахматка ≈(244) — ключ по 255
    # промахивался бы мимо шумных пикселей фона. Для чисто-белого фона среднее ≈255.
    border = _border_pixels(arr)
    return tuple(int(c) for c in border[:, :3].mean(axis=0).round())


def _color_key(arr: np.ndarray, keys, cfg: BackgroundConfig, chroma: bool) -> np.ndarray:
    """Сделать прозрачным фон, близкий к одному из ``keys``. Два порога → мягкий край.

    ``keys`` — список ключевых цветов (1 для solid/white/chroma, 2+ для шахматки).
    Для каждого пикселя берём ближайший ключ. ``ramp`` (0=фон, 1=плотный объект)
    управляет alpha, краевой декантаминацией и дозировкой despill.
    """
    out = arr.copy()
    rgb = arr[:, :, :3]
    soft = max(1.0, float(cfg.softness))
    inner = float(cfg.tolerance)

    K = np.array(keys, dtype=np.float32)
    if len(keys) == 1:                            # быстрый путь (меньше памяти на больших кадрах)
        dist = np.sqrt(((rgb - K[0]) ** 2).sum(axis=2))
        key_map = K[0]
    else:
        d = np.sqrt(((rgb[:, :, None, :] - K[None, None, :, :]) ** 2).sum(axis=3))  # (H,W,k)
        nearest = d.argmin(axis=2)
        dist = np.take_along_axis(d, nearest[:, :, None], axis=2)[:, :, 0]
        key_map = K[nearest]
    ramp = np.clip((dist - inner) / soft, 0.0, 1.0)     # 1 = далеко от фона = объект

    if chroma:
        # хромакей: фоном считаем пиксель, БЛИЗКИЙ к ключу по цвету И с высоким screen.
        # Зелёный/синий ОБЪЕКТ (другой оттенок, далёкий по цвету) сохраняется (ramp_dist=1).
        screen = _screen(rgb, K[0])
        ramp_screen = np.clip((inner + soft - screen) / soft, 0.0, 1.0)
        ramp = np.maximum(ramp, ramp_screen)

    # РЕГИОННОЕ удаление: трогаем только фон, СВЯЗАННЫЙ с краем кадра. Светлые/яркие
    # детали ВНУТРИ объекта не выгрызаются (они не соединены с фоном на границе).
    bg_region = _flood_from_border(dist < (inner + soft))
    lo = 0.18                                     # «поднимаем пол»: слабый край (<18% объекта) → прозрачен
    cleaned = np.clip((ramp - lo) / (1.0 - lo), 0.0, 1.0)
    ramp = np.where(bg_region, cleaned, 1.0)

    out[:, :, 3] = arr[:, :, 3] * ramp

    # краевая декантаминация: убрать подмешанный цвет фона на полупрозрачных пикселях
    out = _decontaminate_edge(out, ramp, key_map)

    if chroma:
        if cfg.despill:
            out = _despill(out, K[0], cfg.despill_strength, weight=(1.0 - ramp))
    else:
        # ИСТИННОЕ ПОКРЫТИЕ на крае: «оправа»/кайма — это краевые пиксели-смеси фона и
        # объекта, которым по цветовому порогу досталась полная alpha. Пересчитываем их
        # alpha как геометрическую долю объекта (насколько пиксель отошёл от фона) и чистим цвет.
        out = _coverage_defringe(out, key_map)

    return out


def _coverage_defringe(out: np.ndarray, key_map) -> np.ndarray:
    """Очистка каймы по ИСТИННОМУ покрытию (для светлого/однотонного фона).

    В полосе ~3px вокруг прозрачного: alpha = доля, на которую пиксель отличается от
    фона B (для светлого фона — насколько потемнел/насытился), а не функция цветового
    расстояния. Затем декантаминация цвета по этому покрытию. Тёмное тело объекта целое.
    """
    a = out[:, :, 3]
    trans = a < 8.0
    if not bool(trans.any()) or bool(trans.all()):
        return out
    band = trans.copy()
    for _ in range(3):
        nb = band.copy()
        nb[1:, :] |= band[:-1, :]; nb[:-1, :] |= band[1:, :]
        nb[:, 1:] |= band[:, :-1]; nb[:, :-1] |= band[:, 1:]
        band = nb
    band &= ~trans & (a > 8.0)
    if not bool(band.any()):
        return out
    km = np.asarray(key_map, dtype=np.float32)
    B = km[None, None, :] if km.ndim == 1 else km            # (H,W,3) цвет фона
    p = out[:, :, :3]
    cov = np.clip(((B - p) / np.maximum(B, 30.0)).max(axis=2), 0.0, 1.0)   # геом. покрытие
    out[:, :, 3] = np.where(band, np.minimum(a, cov * 255.0), a)
    sel = band & (cov < 0.98) & (cov > 1e-3)
    if bool(sel.any()):
        c = cov[sel][:, None]
        rgb = p[sel]
        k = (km[None, :] if km.ndim == 1 else km[sel])
        obj = (rgb - (1.0 - c) * k) / np.maximum(c, 1e-3)
        out[:, :, :3][sel] = np.clip(obj, 0.0, 255.0)
    return out


def _decontaminate_edge(arr: np.ndarray, ramp: np.ndarray, key) -> np.ndarray:
    """Вычесть вклад ключевого цвета фона из RGB на краевых (полупрозрачных) пикселях.

    ``key`` — либо один цвет (3,), либо карта ближайшего ключа на пиксель (H,W,3).
    Для пикселей с 0<ramp<1: obj ≈ (rgb - (1-a)*key)/max(a, eps), клампим в [0,255].
    """
    out = arr.copy()
    eps = 1e-3
    edge = (ramp > eps) & (ramp < 1.0 - eps)
    if not bool(edge.any()):
        return out
    a = ramp[edge][:, None]                       # (N,1) — доля объекта
    rgb = out[:, :, :3][edge]                      # (N,3)
    key = np.asarray(key, dtype=np.float32)
    k = key[None, :] if key.ndim == 1 else key[edge]
    obj = (rgb - (1.0 - a) * k) / np.maximum(a, eps)
    out[:, :, :3][edge] = np.clip(obj, 0.0, 255.0)
    return out


def _screen(rgb: np.ndarray, key: np.ndarray) -> np.ndarray:
    """Сила хромакея в пикселе: g-max(r,b) для зелёного, b-max(r,g) для синего.

    Высоко на пикселях фона, низко/отрицательно на объекте.
    """
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    kr, kg, kb = key
    if kg >= kr and kg >= kb:           # зелёный экран
        return g - np.maximum(r, b)
    if kb >= kr and kb >= kg:           # синий экран
        return b - np.maximum(r, g)
    # не зелёный/синий — деградируем к обычному расстоянию (с инверсией знака)
    return -np.sqrt(((rgb - key) ** 2).sum(axis=2))


def _flood_from_border(cand: np.ndarray) -> np.ndarray:
    """«Волшебная палочка от краёв»: из кандидатов в фон оставить ТОЛЬКО те, что
    связаны (4-связность) с границей кадра. Так светлые детали ВНУТРИ объекта,
    случайно похожие на фон, не удаляются — убирается лишь реальный внешний фон.
    """
    h, w = cand.shape
    if not bool(cand.any()):
        return cand
    small, scale = _downscale_mask_bool(cand, 1100)   # большие — на уменьшенной (топология цела)
    keep_small = _border_connected(small)
    if scale != 1.0:
        keep = np.asarray(Image.fromarray(keep_small.astype(np.uint8) * 255)
                          .resize((w, h), Image.NEAREST)) > 127
    else:
        keep = keep_small
    return keep & cand


def _downscale_mask_bool(mask: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    h, w = mask.shape
    if max(h, w) <= max_side:
        return mask, 1.0
    scale = max_side / max(h, w)
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    small = Image.fromarray(mask.astype(np.uint8) * 255).resize((nw, nh), Image.NEAREST)
    return np.asarray(small) > 127, scale


def _border_connected(mask: np.ndarray) -> np.ndarray:
    """Маска True-пикселей, связанных (4-связность) с границей кадра.
    Run-length + union-find (чистый numpy, без scipy)."""
    h, w = mask.shape
    parent = [0]

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    rows: list[list[tuple[int, int, int]]] = []
    prev: list[tuple[int, int, int]] = []
    nxt = 1
    for y in range(h):
        idx = np.flatnonzero(mask[y])
        runs: list[tuple[int, int, int]] = []
        if idx.size:
            brk = np.flatnonzero(np.diff(idx) > 1)
            starts = np.concatenate(([idx[0]], idx[brk + 1]))
            ends = np.concatenate((idx[brk] + 1, [idx[-1] + 1]))
            for s, e in zip(starts.tolist(), ends.tolist()):
                lbls = [pl for (ps, pe, pl) in prev if s < pe and ps < e]   # 4-связность
                if lbls:
                    lb = find(lbls[0])
                    for o in lbls[1:]:
                        union(lb, o)
                    lb = find(lb)
                else:
                    lb = nxt; parent.append(nxt); nxt += 1
                runs.append((s, e, lb))
        rows.append(runs)
        prev = runs

    border = set()
    for y, runs in enumerate(rows):
        on_hborder = (y == 0 or y == h - 1)
        for s, e, lb in runs:
            if on_hborder or s == 0 or e == w:
                border.add(find(lb))
    keep = np.zeros((h, w), dtype=bool)
    for y, runs in enumerate(rows):
        for s, e, lb in runs:
            if find(lb) in border:
                keep[y, s:e] = True
    return keep


def _despill(arr: np.ndarray, key: np.ndarray, strength: float, weight=None) -> np.ndarray:
    """Убрать цветную кайму: подрезать доминирующий канал хромакея.

    ``weight`` — карта силы despill 0..1 (та же форма, что и изображение). Если
    задана, эффект масштабируется по ней: у плотного непрозрачного объекта
    (weight≈0) despill не трогает цвет — легитимная зелень/синь не сереет. Если
    не задана — поведение прежнее (despill по всему кадру).
    """
    out = arr.copy()
    r, g, b = out[:, :, 0], out[:, :, 1], out[:, :, 2]
    kr, kg, kb = key
    s = float(np.clip(strength, 0.0, 1.5))
    if weight is not None:
        w = np.clip(weight, 0.0, 1.0)
    else:
        w = 1.0
    if kg >= kr and kg >= kb:           # зелёный: g не должен превышать среднее r,b
        cap = (r + b) / 2.0
        excess = np.clip(g - cap, 0, None) * s * w
        out[:, :, 1] = np.clip(g - excess, 0, 255)   # при strength>1 не уходим в минус
    elif kb >= kr and kb >= kg:         # синий
        cap = (r + g) / 2.0
        excess = np.clip(b - cap, 0, None) * s * w
        out[:, :, 2] = np.clip(b - excess, 0, 255)
    return out


def _clean_existing_alpha(arr: np.ndarray) -> np.ndarray:
    """Нормализовать уже прозрачную картинку: убрать почти-нулевой шум по alpha."""
    out = arr.copy()
    a = out[:, :, 3]
    a = np.where(a < 4, 0.0, a)   # подавляем «грязь» из почти-прозрачных пикселей
    out[:, :, 3] = a
    return out


# --- AI (опционально) ------------------------------------------------------

def _remove_ai(im: Image.Image) -> tuple[Image.Image, list[str]]:
    try:
        from rembg import remove as _rembg_remove  # type: ignore
    except Exception:  # noqa: BLE001 — любой импорт-фейл = нет AI
        return im, [
            "AI-режим недоступен: установите `pip install rembg onnxruntime` "
            "(модель скачается при первом запуске). Фон не изменён."
        ]
    try:
        out = _rembg_remove(im)
        if out.mode != "RGBA":
            out = out.convert("RGBA")
        return out, ["AI (rembg/u2net) применён"]
    except Exception as exc:  # noqa: BLE001
        return im, [f"AI-режим упал: {exc}. Фон не изменён."]


# --- утилиты ---------------------------------------------------------------

def _to_img(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="RGBA")
