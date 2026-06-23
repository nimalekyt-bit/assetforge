"""Adversarial stress tests for object splitting in assetforge.core.detect.

Generates synthetic RGBA images (transparent bg + opaque blobs) where the
TRUE number of objects is known, runs split_objects in several modes, and
reports where the count / boxes diverge from ground truth.

Run:  PYTHONIOENCODING=utf-8 python design/stress_split.py
"""
from __future__ import annotations

import time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from assetforge.core import detect


# ---------- helpers ----------

def canvas(w, h):
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def fill_rect(im, box, color=(255, 0, 0, 255)):
    ImageDraw.Draw(im).rectangle(box, fill=color)


def fill_ellipse(im, box, color=(0, 120, 255, 255)):
    ImageDraw.Draw(im).ellipse(box, fill=color)


def iou(a, b):
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua if ua else 0.0


def run(name, im, expected, mode="auto", merge_distance=0, min_area=64,
        grid_rows=0, grid_cols=0, gap_frac=0.04, verbose=True):
    t0 = time.perf_counter()
    boxes = detect.split_objects(im, mode=mode, merge_distance=merge_distance,
                                 min_area=min_area, grid_rows=grid_rows,
                                 grid_cols=grid_cols, gap_frac=gap_frac)
    dt = (time.perf_counter() - t0) * 1000
    got = len(boxes)
    status = "OK " if got == expected else "!! "
    if verbose:
        print(f"{status}[{name}] mode={mode} md={merge_distance} "
              f"expected={expected} got={got}  ({dt:.0f} ms)")
        if got != expected:
            print(f"     boxes={boxes}")
    return got, boxes, dt


print("=" * 78)
print("SPLIT OBJECTS STRESS — expected vs got (auto + objects modes)")
print("=" * 78)

results = []

# ---------------------------------------------------------------------------
# 1) DENSE GRID, small gaps — 6x6 squares, gap = 2px between 30px tiles
# ---------------------------------------------------------------------------
im = canvas(400, 400)
n = 0
for r in range(6):
    for c in range(6):
        x = 10 + c * 64
        y = 10 + r * 64
        fill_rect(im, (x, y, x + 60, y + 60))
        n += 1
results.append(("dense_grid_6x6_gap4", *run("dense_grid_6x6 gap4", im, 36, mode="objects")))

# dense grid with TINY 1px gaps (tiles 40px, gap 1)
im = canvas(410, 410)
for r in range(10):
    for c in range(10):
        x = 5 + c * 41
        y = 5 + r * 41
        fill_rect(im, (x, y, x + 39, y + 39))
results.append(("dense_grid_10x10_gap2", *run("dense_grid_10x10 gap2", im, 100, mode="objects")))

# ---------------------------------------------------------------------------
# 2) ROW / COLUMN layouts
# ---------------------------------------------------------------------------
im = canvas(800, 120)
for c in range(8):
    x = 10 + c * 98
    fill_rect(im, (x, 30, x + 80, 100))
results.append(("row_of_8", *run("row_of_8", im, 8, mode="objects")))

im = canvas(120, 800)
for r in range(8):
    y = 10 + r * 98
    fill_rect(im, (30, y, 100, y + 80))
results.append(("col_of_8", *run("col_of_8", im, 8, mode="objects")))

# ---------------------------------------------------------------------------
# 3) SCATTERED assets (random non-overlapping)
# ---------------------------------------------------------------------------
rng = np.random.default_rng(42)
im = canvas(600, 600)
placed = []
count = 0
tries = 0
while count < 12 and tries < 2000:
    tries += 1
    w_ = rng.integers(30, 70); h_ = rng.integers(30, 70)
    x = rng.integers(0, 600 - w_); y = rng.integers(0, 600 - h_)
    box = (x, y, x + w_, y + h_)
    # keep >=15px apart
    ok = all(not (box[0] < p[2] + 15 and p[0] < box[2] + 15 and
                  box[1] < p[3] + 15 and p[1] < box[3] + 15) for p in placed)
    if ok:
        placed.append(box); fill_ellipse(im, box); count += 1
results.append(("scattered_12", *run("scattered_12", im, 12, mode="objects")))

# ---------------------------------------------------------------------------
# 4) TOUCHING assets (share an edge) — should this be 1 or N? gt-ambiguous.
#    We report what engine does. 3 squares touching in a row.
# ---------------------------------------------------------------------------
im = canvas(400, 150)
fill_rect(im, (20, 30, 120, 120), (255, 0, 0, 255))
fill_rect(im, (120, 30, 220, 120), (0, 255, 0, 255))  # touches first
fill_rect(im, (220, 30, 320, 120), (0, 0, 255, 255))  # touches second
results.append(("touching_3_inline", *run("touching_3 (edge-shared)", im, 3, mode="objects")))

# ---------------------------------------------------------------------------
# 5) STRONGLY DIFFERENT sizes — 1 huge + 5 tiny separate icons
# ---------------------------------------------------------------------------
im = canvas(700, 400)
fill_rect(im, (20, 20, 420, 380), (200, 200, 0, 255))   # huge 400x360
for i in range(5):
    x = 460
    y = 20 + i * 70
    fill_rect(im, (x, y, x + 40, y + 40), (255, 0, 255, 255))  # tiny 40x40
# tiny area = 1600, huge area = 144000; 1600 < 0.12*144000=17280 -> fragments!
results.append(("huge_plus_5_tiny", *run("huge + 5 tiny (far apart)", im, 6, mode="objects")))

# ---------------------------------------------------------------------------
# 6) WORDMARK (letters) — render text; expect ONE logical object in auto.
# ---------------------------------------------------------------------------
im = canvas(600, 160)
d = ImageDraw.Draw(im)
try:
    font = ImageFont.truetype("arial.ttf", 90)
except Exception:
    font = ImageFont.load_default()
d.text((20, 20), "BRAND", fill=(255, 255, 255, 255), font=font)
# count letters as separate components in 'objects'
g_obj, b_obj, _ = run("wordmark BRAND objects", im, 5, mode="objects")
g_auto, b_auto, _ = run("wordmark BRAND auto", im, 1, mode="auto")
results.append(("wordmark_objects", g_obj, b_obj, 0))
results.append(("wordmark_auto", g_auto, b_auto, 0))

# ---------------------------------------------------------------------------
# 7) SINGLE logo with detached parts (i-dots, sparkles, glow) — expect 1.
# ---------------------------------------------------------------------------
im = canvas(400, 400)
fill_ellipse(im, (120, 150, 280, 310), (0, 200, 120, 255))   # main blob
fill_ellipse(im, (185, 60, 215, 90), (0, 200, 120, 255))     # detached dot above
fill_rect(im, (60, 90, 75, 105), (255, 255, 0, 255))         # sparkle far away
fill_rect(im, (330, 100, 342, 112), (255, 255, 0, 255))      # sparkle far away
results.append(("logo_detached_parts", *run("single logo + dot + 2 sparkles", im, 1, mode="auto")))

# ---------------------------------------------------------------------------
# 8) 50+ small dots
# ---------------------------------------------------------------------------
im = canvas(800, 800)
k = 0
for r in range(8):
    for c in range(8):
        x = 20 + c * 96; y = 20 + r * 96
        fill_ellipse(im, (x, y, x + 24, y + 24))  # 64 dots
        k += 1
results.append(("dots_64", *run("dots_64", im, 64, mode="objects")))

# ---------------------------------------------------------------------------
# 9) EXTREMELY ELONGATED objects
# ---------------------------------------------------------------------------
im = canvas(1000, 200)
fill_rect(im, (10, 90, 480, 110), (255, 0, 0, 255))   # 470x20 bar
fill_rect(im, (520, 90, 990, 110), (0, 0, 255, 255))  # second bar
results.append(("elongated_2_bars", *run("2 elongated bars", im, 2, mode="objects")))

# very thin 1px tall lines
im = canvas(600, 400)
for i in range(10):
    y = 20 + i * 38
    fill_rect(im, (20, y, 580, y + 2), (0, 0, 0, 255))  # 3px tall lines
results.append(("thin_lines_10", *run("10 thin lines", im, 10, mode="objects")))

print()
print("=" * 78)
print("SUMMARY (mismatches):")
for name, got, boxes, dt in results:
    pass
print("=" * 78)
