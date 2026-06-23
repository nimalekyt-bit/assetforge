"""Поиск контента по alpha: bbox и разделение на несколько объектов.

Разделение объектов — рекурсивный **XY-cut** (проекция маски на строки/столбцы,
рез по достаточно широким пустым полосам). Полностью векторизовано (быстро даже
на больших картинках) и идеально ложится на типовой кейс: несколько логотипов,
разнесённых промежутками (как вордмарк + эмблема в примерах).
"""
from __future__ import annotations

import numpy as np
from PIL import Image

BBox = tuple[int, int, int, int]  # (left, top, right, bottom), правый/нижний исключительные


def alpha_mask(im: Image.Image, threshold: int = 16) -> np.ndarray:
    """Булева маска «здесь контент» по alpha > threshold."""
    a = np.asarray(im.convert("RGBA"))[:, :, 3]
    return a > threshold


def content_bbox(im: Image.Image, threshold: int = 16) -> BBox | None:
    """BBox контента по alpha>threshold (полупрозрачный «мусор» не раздувает рамку)."""
    mask = alpha_mask(im, threshold)
    return _mask_bbox(mask)


def split_objects(
    im: Image.Image,
    threshold: int = 16,
    min_area: int = 16,
    mode: str = "auto",
    gap_frac: float = 0.04,
    merge_distance: int = 0,
    grid_rows: int = 0,
    grid_cols: int = 0,
) -> list[BBox]:
    """Список bbox объектов.

    mode:
      - ``single``  — один общий bbox;
      - ``auto``    — авто-определение: связные области (connected-components); если
        объект один — возвращается единым bbox без лишнего дробления;
      - ``objects`` — каждая связная область = отдельный ассет (всегда списком);
      - ``grid``    — равномерная сетка ``grid_rows`` × ``grid_cols`` (для спрайт-листов);
      - ``xycut``   — старый рекурсивный XY-cut (рез по сплошным пустым полосам).
    merge_distance — на сколько пикселей «склеивать» близкие части (чтобы буквы/части
      одного лого не дробились); больше — крупнее группы, меньше — дробит сильнее.
    """
    mask = alpha_mask(im, threshold)
    full = _mask_bbox(mask)
    if full is None:
        return []
    mode = (mode or "auto").lower()

    if mode == "single":
        return [_as_int(full)]

    if mode == "grid":
        boxes = grid_slice(im, max(1, int(grid_rows)), max(1, int(grid_cols)),
                           threshold=threshold, min_area=max(1, min_area))
        return boxes or [_as_int(full)]

    if mode == "xycut":
        h, w = mask.shape
        min_gap = max(4, int(min(h, w) * gap_frac))
        boxes = [b for b in _xy_cut(mask, 0, 0, min_gap) if _area(mask, b) >= min_area]
        if not boxes:
            return [_as_int(full)]
        boxes = [_as_int(b) for b in boxes]
        boxes.sort(key=lambda b: (b[1], b[0]))
        return boxes

    # auto | objects | split — разметка связных областей
    boxes = connected_components(im, threshold=threshold, min_area=min_area,
                                 merge_distance=merge_distance)
    if not boxes:
        # связных областей не нашлось — НЕ выдумываем фейковый bbox на весь лист
        return []
    if mode == "auto" and len(boxes) == 1:
        return [_as_int(full)]
    return boxes


def _as_int(b: BBox) -> BBox:
    return tuple(int(v) for v in b)



# --- XY-cut ----------------------------------------------------------------

def _xy_cut(mask: np.ndarray, off_x: int, off_y: int, min_gap: int, depth: int = 0) -> list[BBox]:
    """Рекурсивно резать область по самым широким пустым полосам (строки, затем столбцы)."""
    bb = _mask_bbox(mask)
    if bb is None:
        return []
    x0, y0, x1, y1 = bb
    sub = mask[y0:y1, x0:x1]

    if depth > 12:  # страховка от бесконечной рекурсии
        return [(off_x + x0, off_y + y0, off_x + x1, off_y + y1)]

    # пробуем горизонтальный рез (по пустым строкам), потом вертикальный
    for axis in (1, 0):
        segments = _segments(sub.any(axis=axis), min_gap)
        if len(segments) > 1:
            out: list[BBox] = []
            for s, e in segments:
                if axis == 1:  # делим по строкам (вертикально)
                    piece = sub[s:e, :]
                    out += _xy_cut(piece, off_x + x0, off_y + y0 + s, min_gap, depth + 1)
                else:           # делим по столбцам (горизонтально)
                    piece = sub[:, s:e]
                    out += _xy_cut(piece, off_x + x0 + s, off_y + y0, min_gap, depth + 1)
            return out

    return [(off_x + x0, off_y + y0, off_x + x1, off_y + y1)]


def _segments(profile: np.ndarray, min_gap: int) -> list[tuple[int, int]]:
    """Диапазоны непрерывного контента в 1D-профиле, разделённые пустотами >= min_gap."""
    idx = np.where(profile)[0]
    if len(idx) == 0:
        return []
    # границы пустых промежутков
    gaps = np.where(np.diff(idx) > min_gap)[0]
    starts = [idx[0]] + [idx[g + 1] for g in gaps]
    ends = [idx[g] + 1 for g in gaps] + [idx[-1] + 1]
    return list(zip(starts, ends))


# --- утилиты ---------------------------------------------------------------

def _mask_bbox(mask: np.ndarray) -> BBox | None:
    ys = np.where(mask.any(axis=1))[0]
    xs = np.where(mask.any(axis=0))[0]
    if len(ys) == 0 or len(xs) == 0:
        return None
    return int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1


def _area(mask: np.ndarray, bb: BBox) -> int:
    x0, y0, x1, y1 = bb
    return int(mask[y0:y1, x0:x1].sum())


# --- connected components (разметка связных областей) ----------------------

_LABEL_MAX_SIDE = 720   # маска ужимается до этой стороны для быстрой разметки
_MAX_DILATE = 40        # потолок итераций «склейки» (защита по скорости)
_GRID_MAX_CELLS = 400   # потолок rows*cols в grid-режиме (иначе тысячи микро-боксов)


def connected_components(im: Image.Image, threshold: int = 16, min_area: int = 16,
                         merge_distance: int = 0) -> list[BBox]:
    """Каждая связная область контента (по alpha) -> отдельный bbox.

    Надёжно находит N отдельных ассетов на листе при любой раскладке (в отличие от
    XY-cut, которому нужны сплошные пустые полосы). ``merge_distance`` склеивает близкие
    части одного объекта. Разметка идёт на уменьшенной маске (быстро), затем каждый bbox
    масштабируется обратно и уточняется по полной маске пиксель-в-пиксель.
    """
    mask = alpha_mask(im, threshold)
    if _mask_bbox(mask) is None:
        return []
    small, scale = _downscale_mask(mask, _LABEL_MAX_SIDE)
    if merge_distance > 0:
        small = _dilate(small, max(1, min(_MAX_DILATE, round(merge_distance * scale))))

    H, W = mask.shape
    inv = 1.0 / scale
    raw: list[tuple[BBox, int]] = []
    for (x0, y0, x1, y1) in _label_runs(small):
        fx0 = max(0, int(x0 * inv) - 1); fy0 = max(0, int(y0 * inv) - 1)
        fx1 = min(W, int(round(x1 * inv)) + 1); fy1 = min(H, int(round(y1 * inv)) + 1)
        rb = _mask_bbox(mask[fy0:fy1, fx0:fx1])      # уточняем по полной маске
        if rb is None:
            continue
        box = (fx0 + rb[0], fy0 + rb[1], fx0 + rb[2], fy0 + rb[3])
        raw.append((_as_int(box), _area(mask, box)))

    # умная сборка: мелкие осколки (анти-алиас, искры, точки) прикрепляем к близкой
    # КРУПНОЙ области, но разные крупные ассеты НЕ сливаем — даже если они рядом.
    # max_gap — небольшой АБСОЛЮТНЫЙ порог (потолок ~12px): на больших холстах
    # относительные десятки px съедали соседние самостоятельные иконки.
    boxes = _merge_fragments(raw, min_area, max_gap=min(12, max(2, round(min(H, W) * 0.01))))
    return _sort_reading_order(boxes)


def _is_micro_fragment(b: BBox, a: int, min_area: int) -> bool:
    """Осколок «для прикрепления»: мал в АБСОЛЮТЕ (анти-алиас, искра, i-точка), а не
    просто относительно крупнейшего объекта. Только такие можно поглощать соседней
    крупной областью; настоящая (пусть и небольшая) иконка остаётся самостоятельной."""
    w = b[2] - b[0]; h = b[3] - b[1]
    return a < min_area * 4 and max(w, h) < 12


def _merge_fragments(raw: list[tuple[BBox, int]], min_area: int, max_gap: float) -> list[BBox]:
    """raw = [(bbox, площадь)]. Возвращает крупные области + прикреплённые МИКРО-осколки."""
    if not raw:
        return []
    amax = max(a for _, a in raw)
    main = [list(b) for b, a in raw if a >= amax * 0.12 and a >= min_area]
    if not main:
        # даже крупнейший компонент под порогом min_area: НЕ схлопываем всё в один
        # фейковый bbox — отдаём под-пороговые боксы как есть (это могут быть мелкие ассеты).
        return [tuple(int(v) for v in b) for b, _ in raw]
    for b, a in raw:
        if a >= amax * 0.12 and a >= min_area:
            continue                               # это «крупная» область, уже в main
        if _is_micro_fragment(b, a, min_area):
            gi, best = -1, 1e18
            for i, m in enumerate(main):
                g = _bbox_gap(b, m)
                if g < best:
                    best, gi = g, i
            if gi >= 0 and best <= max_gap:        # микро-осколок рядом с крупной — прикрепляем
                m = main[gi]
                m[0] = min(m[0], b[0]); m[1] = min(m[1], b[1])
                m[2] = max(m[2], b[2]); m[3] = max(m[3], b[3])
                continue
        if a >= min_area:                          # самостоятельный объект (не микро-шум)
            main.append(list(b))
    return [tuple(int(v) for v in m) for m in main]


def _bbox_gap(a: BBox, b: BBox) -> float:
    """Зазор между двумя bbox (0 при пересечении)."""
    gx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    gy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    return (gx * gx + gy * gy) ** 0.5



def grid_slice(im: Image.Image, rows: int, cols: int, threshold: int = 16,
               min_area: int = 1) -> list[BBox]:
    """Нарезать контент равномерной сеткой rows×cols; пустые ячейки пропускаем,
    непустые — обрезаем до их реального контента."""
    mask = alpha_mask(im, threshold)
    full = _mask_bbox(mask)
    if full is None:
        return []
    x0, y0, x1, y1 = full
    rows = max(1, int(rows)); cols = max(1, int(cols))
    if rows * cols > _GRID_MAX_CELLS:              # защита от тысяч микро-ячеек (grid 64×64→4096)
        k = (_GRID_MAX_CELLS / (rows * cols)) ** 0.5
        rows = max(1, int(rows * k)); cols = max(1, int(cols * k))
    cw = (x1 - x0) / cols; ch = (y1 - y0) / rows
    out: list[BBox] = []
    for r in range(rows):
        for c in range(cols):
            cx0 = int(round(x0 + c * cw)); cx1 = int(round(x0 + (c + 1) * cw))
            cy0 = int(round(y0 + r * ch)); cy1 = int(round(y0 + (r + 1) * ch))
            rb = _mask_bbox(mask[cy0:cy1, cx0:cx1])
            if rb is None:
                continue
            box = (cx0 + rb[0], cy0 + rb[1], cx0 + rb[2], cy0 + rb[3])
            if _area(mask, box) >= min_area:
                out.append(_as_int(box))
    return out


def _downscale_mask(mask: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    h, w = mask.shape
    if max(h, w) <= max_side:
        return mask, 1.0
    scale = max_side / max(h, w)
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    small = Image.fromarray(mask.astype(np.uint8) * 255).resize((nw, nh), Image.NEAREST)
    return np.asarray(small) > 127, scale


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    """Бинарная дилатация на r итераций (8-связность) — «склеивает» близкие пиксели."""
    m = mask
    for _ in range(int(r)):
        d = m.copy()
        d[1:, :] |= m[:-1, :]; d[:-1, :] |= m[1:, :]
        d[:, 1:] |= m[:, :-1]; d[:, :-1] |= m[:, 1:]
        d[1:, 1:] |= m[:-1, :-1]; d[:-1, :-1] |= m[1:, 1:]
        d[1:, :-1] |= m[:-1, 1:]; d[:-1, 1:] |= m[1:, :-1]
        m = d
    return m


def _label_runs(mask: np.ndarray) -> list[BBox]:
    """Connected-components (8-связность) методом run-length + union-find.
    Возвращает bbox'ы в координатах переданной (уменьшенной) маски."""
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

    prev: list[tuple[int, int, int]] = []
    all_runs: list[tuple[int, int, int, int]] = []
    nxt = 1
    for y in range(h):
        idx = np.flatnonzero(mask[y])
        runs: list[tuple[int, int, int]] = []
        if idx.size:
            brk = np.flatnonzero(np.diff(idx) > 1)
            starts = np.concatenate(([idx[0]], idx[brk + 1]))
            ends = np.concatenate((idx[brk] + 1, [idx[-1] + 1]))
            for s, e in zip(starts.tolist(), ends.tolist()):
                lbls = [pl for (ps, pe, pl) in prev if s <= pe and ps <= e]  # 8-связность
                if lbls:
                    lb = find(lbls[0])
                    for o in lbls[1:]:
                        union(lb, o)
                    lb = find(lb)
                else:
                    lb = nxt; parent.append(nxt); nxt += 1
                runs.append((s, e, lb))
                all_runs.append((s, e, lb, y))
        prev = runs

    boxes: dict[int, list[int]] = {}
    for s, e, lb, y in all_runs:
        root = find(lb)
        b = boxes.get(root)
        if b is None:
            boxes[root] = [s, y, e, y + 1]
        else:
            b[0] = min(b[0], s); b[1] = min(b[1], y)
            b[2] = max(b[2], e); b[3] = max(b[3], y + 1)
    return [tuple(v) for v in boxes.values()]


def _sort_reading_order(boxes: list[BBox]) -> list[BBox]:
    """Упорядочить bbox'ы как читают: по строкам сверху-вниз, внутри строки слева-направо."""
    if not boxes:
        return []
    heights = sorted(b[3] - b[1] for b in boxes)
    tol = max(8, heights[len(heights) // 2] * 0.5)   # допуск «та же строка» ~ полвысоты
    rows: list[list[BBox]] = []
    for b in sorted(boxes, key=lambda b: b[1]):
        for row in rows:
            if abs(b[1] - row[0][1]) <= tol:
                row.append(b)
                break
        else:
            rows.append([b])
    out: list[BBox] = []
    for row in sorted(rows, key=lambda r: min(x[1] for x in r)):
        out.extend(sorted(row, key=lambda b: b[0]))
    return out

