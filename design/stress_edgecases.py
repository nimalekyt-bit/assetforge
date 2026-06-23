"""Adversarial edge-case stress tests for AssetForge engine.

Covers: empty/transparent, 1x1, solid fill, huge (4000x4000 timing/mem),
extreme aspect ratio, full-frame photo (no bg), dirty alpha (dark fringe).
Measures numerically. Engine is NOT modified — only read & tested.
"""
from __future__ import annotations

import gc
import time
import tracemalloc

import numpy as np
from PIL import Image

from assetforge.core.background import remove_background, detect_background
from assetforge.core import detect
from assetforge.core.config import BackgroundConfig, PipelineConfig
from assetforge.core import pipeline


def arr_of(im):
    return np.asarray(im.convert("RGBA"))


def transp_frac(im):
    a = arr_of(im)[:, :, 3]
    return float((a < 16).mean())


def alpha_at(im, frac_x, frac_y):
    a = arr_of(im)[:, :, 3]
    h, w = a.shape
    return int(a[min(h - 1, int(h * frac_y)), min(w - 1, int(w * frac_x))])


def corner_center(im):
    a = arr_of(im)[:, :, 3]
    h, w = a.shape
    return {
        "tl": int(a[0, 0]), "tr": int(a[0, w - 1]),
        "bl": int(a[h - 1, 0]), "br": int(a[h - 1, w - 1]),
        "center": int(a[h // 2, w // 2]),
    }


def composite_on(im, bg_rgb):
    """Composite RGBA over solid bg, return resulting RGB array (uint8)."""
    a = arr_of(im).astype(np.float32)
    al = a[:, :, 3:4] / 255.0
    bg = np.array(bg_rgb, dtype=np.float32)
    out = a[:, :, :3] * al + bg[None, None, :] * (1.0 - al)
    return np.clip(out, 0, 255).astype(np.uint8)


def section(name):
    print("\n" + "=" * 70)
    print(name)
    print("=" * 70)


# ---------------------------------------------------------------------------
section("1. EMPTY / FULLY TRANSPARENT")

empty = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
try:
    mode, info = detect_background(arr_of(empty).astype(np.float32))
    print(f"detect_background -> {mode!r} ({info})")
except Exception as e:
    print(f"detect_background RAISED: {type(e).__name__}: {e}")

try:
    r = remove_background(empty, BackgroundConfig(mode="auto"))
    print(f"remove_background auto -> detected={r.detected_mode!r} transp={transp_frac(r.image):.2%} notes={r.notes}")
except Exception as e:
    print(f"remove_background auto RAISED: {type(e).__name__}: {e}")

for m in ("white", "solid", "alpha", "chroma"):
    try:
        r = remove_background(empty, BackgroundConfig(mode=m))
        print(f"  mode={m}: detected={r.detected_mode} transp={transp_frac(r.image):.2%}")
    except Exception as e:
        print(f"  mode={m} RAISED: {type(e).__name__}: {e}")

for sm in ("auto", "objects", "grid", "single", "xycut"):
    try:
        boxes = detect.split_objects(empty, mode=sm)
        print(f"  split({sm}) -> {len(boxes)} boxes")
    except Exception as e:
        print(f"  split({sm}) RAISED: {type(e).__name__}: {e}")

# Full pipeline.run on empty
try:
    res = pipeline.run(empty)
    print(f"pipeline.run(empty) -> {len(res)} export results (no crash expected)")
except Exception as e:
    print(f"pipeline.run(empty) RAISED: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
section("2. 1x1 IMAGES")

for col, label in [((255, 255, 255, 255), "white opaque"),
                   ((0, 0, 0, 255), "black opaque"),
                   ((0, 0, 0, 0), "transparent"),
                   ((0, 200, 0, 255), "green")]:
    im = Image.new("RGBA", (1, 1), col)
    try:
        mode, info = detect_background(arr_of(im).astype(np.float32))
        r = remove_background(im, BackgroundConfig(mode="auto"))
        print(f"1x1 {label}: detect={mode!r}({info}) remove_detected={r.detected_mode} "
              f"alpha={alpha_at(r.image,0,0)}")
    except Exception as e:
        print(f"1x1 {label} RAISED: {type(e).__name__}: {e}")
    for sm in ("auto", "objects", "grid"):
        try:
            boxes = detect.split_objects(im, mode=sm)
            print(f"    split({sm}) -> {boxes}")
        except Exception as e:
            print(f"    split({sm}) RAISED: {type(e).__name__}: {e}")
    # white mode color-key on a 1x1 (broadcast edge case)
    try:
        r = remove_background(im, BackgroundConfig(mode="white"))
        print(f"    white-mode alpha={alpha_at(r.image,0,0)}")
    except Exception as e:
        print(f"    white-mode RAISED: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
section("3. SOLID COLOR FILL (single-color frame)")

for col, label in [((255, 255, 255, 255), "pure white"),
                   ((128, 128, 128, 255), "mid gray"),
                   ((0, 100, 200, 255), "blue solid"),
                   ((10, 10, 10, 255), "near black")]:
    im = Image.new("RGBA", (256, 256), col)
    mode, info = detect_background(arr_of(im).astype(np.float32))
    r = remove_background(im, BackgroundConfig(mode="auto"))
    tf = transp_frac(r.image)
    print(f"solid {label}: detect={mode!r}({info}) removed transp={tf:.1%} "
          f"-> {'PRESERVED' if tf < 0.5 else 'WIPED'}")
    # And forced white/solid: does it wipe the whole canvas to nothing?
    r2 = remove_background(im, BackgroundConfig(mode="white"))
    print(f"    forced white-mode transp={transp_frac(r2.image):.1%}")
    boxes = detect.split_objects(r.image, mode="auto")
    print(f"    objects after auto-bg: {len(boxes)}")


# ---------------------------------------------------------------------------
section("4. HUGE IMAGE 4000x4000 — TIME & PEAK MEMORY")

def make_logo_canvas(W, H, n_blobs=3):
    """White bg with a few colored blobs."""
    im = Image.new("RGBA", (W, H), (250, 250, 250, 255))
    px = im.load()
    rng = np.random.default_rng(0)
    a = np.asarray(im).copy()
    for _ in range(n_blobs):
        cx, cy = rng.integers(W // 6, W - W // 6), rng.integers(H // 6, H - H // 6)
        rad = min(W, H) // 8
        yy, xx = np.ogrid[:H, :W]
        m = (xx - cx) ** 2 + (yy - cy) ** 2 <= rad * rad
        a[m, 0] = int(rng.integers(0, 255))
        a[m, 1] = int(rng.integers(0, 255))
        a[m, 2] = int(rng.integers(0, 255))
    return Image.fromarray(a, "RGBA")

for W, H in [(4000, 4000)]:
    big = make_logo_canvas(W, H)
    print(f"image {W}x{H} ({W*H/1e6:.1f} MP)")

    gc.collect(); tracemalloc.start()
    t0 = time.perf_counter()
    r = remove_background(big, BackgroundConfig(mode="auto"))
    t_bg = time.perf_counter() - t0
    cur, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    print(f"  remove_background auto: {t_bg*1000:.0f} ms, peak +{peak/1e6:.0f} MB, "
          f"detected={r.detected_mode}, transp={transp_frac(r.image):.1%}")

    fg = r.image
    for sm in ("auto", "objects", "xycut"):
        gc.collect(); tracemalloc.start()
        t0 = time.perf_counter()
        boxes = detect.split_objects(fg, mode=sm)
        dt = time.perf_counter() - t0
        cur, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
        print(f"  split({sm}): {dt*1000:.0f} ms, peak +{peak/1e6:.0f} MB, {len(boxes)} boxes")

    # full analyze (the UI entry point)
    gc.collect(); tracemalloc.start()
    t0 = time.perf_counter()
    an = pipeline.analyze(big)
    dt = time.perf_counter() - t0
    cur, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    print(f"  pipeline.analyze: {dt*1000:.0f} ms, peak +{peak/1e6:.0f} MB, "
          f"objects={an.meta['objects']}, size kept={an.meta['size']}")

# Forced white mode on huge (color-key full 4000x4000 float64 distance math)
big2 = make_logo_canvas(4000, 4000)
gc.collect(); tracemalloc.start()
t0 = time.perf_counter()
r = remove_background(big2, BackgroundConfig(mode="white"))
dt = time.perf_counter() - t0
cur, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
print(f"  remove_background WHITE 4000x4000: {dt*1000:.0f} ms, peak +{peak/1e6:.0f} MB")

# Forced solid mode (2 keys path triggers (H,W,k,3) broadcast)
gc.collect(); tracemalloc.start()
t0 = time.perf_counter()
r = remove_background(big2, BackgroundConfig(mode="solid"))
dt = time.perf_counter() - t0
cur, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
print(f"  remove_background SOLID 4000x4000: {dt*1000:.0f} ms, peak +{peak/1e6:.0f} MB")


# ---------------------------------------------------------------------------
section("5. EXTREME ASPECT RATIO")

for W, H, label in [(8000, 4, "8000x4 sliver"),
                    (4, 8000, "4x8000 sliver"),
                    (10000, 10, "10000x10 banner")]:
    a = np.full((H, W, 4), 255, np.uint8)
    # put a small dark mark in the middle
    a[:, W // 2 - 1:W // 2 + 1, :3] = 0
    im = Image.fromarray(a, "RGBA")
    try:
        t0 = time.perf_counter()
        r = remove_background(im, BackgroundConfig(mode="auto"))
        boxes = detect.split_objects(r.image, mode="auto")
        dt = time.perf_counter() - t0
        print(f"{label}: detect={r.detected_mode} transp={transp_frac(r.image):.1%} "
              f"boxes={len(boxes)} {dt*1000:.0f}ms")
    except Exception as e:
        print(f"{label} RAISED: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
section("6. FULL-FRAME PHOTO (no obvious background)")

rng = np.random.default_rng(42)
# busy noisy photo: gradient + noise, no uniform border
yy, xx = np.mgrid[0:512, 0:512]
base = (xx / 512 * 200).astype(np.float32)
noise = rng.normal(0, 40, (512, 512, 3))
photo = np.clip(base[:, :, None] + noise + np.array([30, 60, 90]), 0, 255).astype(np.uint8)
photo = np.dstack([photo, np.full((512, 512), 255, np.uint8)])
pim = Image.fromarray(photo, "RGBA")
mode, info = detect_background(arr_of(pim).astype(np.float32))
r = remove_background(pim, BackgroundConfig(mode="auto"))
print(f"noisy photo: detect={mode!r}({info}) removed transp={transp_frac(r.image):.1%}")
boxes = detect.split_objects(r.image, mode="auto")
print(f"  objects={len(boxes)}")
# what if user FORCES white on a photo? does it punch holes?
r2 = remove_background(pim, BackgroundConfig(mode="white"))
print(f"  forced white on photo: transp={transp_frac(r2.image):.1%} (holes punched in subject?)")


# ---------------------------------------------------------------------------
section("7. DIRTY ALPHA (dark fringe / halo around object)")

# Object = white square on white bg, but with a dark anti-alias fringe ring.
W = H = 300
a = np.full((H, H, 4), 255, np.uint8)  # white bg
# central red object
a[100:200, 100:200, :3] = [220, 40, 40]
# DARK FRINGE: 2px dark ring around object (contamination)
for d in (98, 99, 200, 201):
    a[d, 98:202, :3] = [20, 20, 20]
    a[98:202, d, :3] = [20, 20, 20]
im = Image.fromarray(a, "RGBA")
r = remove_background(im, BackgroundConfig(mode="auto"))
print(f"dirty-fringe: detect={r.detected_mode} transp={transp_frac(r.image):.1%}")
# Composite over dark and light — check for halo (residual bright/dark ring)
for bg, name in [((0, 0, 0), "black"), ((255, 0, 255), "magenta")]:
    comp = composite_on(r.image, bg)
    # sample fringe ring location (~row 99) vs interior
    ring = comp[99, 100:200].mean(axis=0)
    print(f"  composite on {name}: fringe-row mean RGB={ring.round(0)}")

# Now classic case: chroma key on green with dark spill border (halo test)
W = H = 300
a = np.full((H, W, 4), 0, np.uint8)
a[:, :, 1] = 200  # green screen
a[:, :, 3] = 255
# object: orange square with semi-transparent green-tinted edge
a[100:200, 100:200] = [240, 140, 30, 255]
# edge contamination: blend green into 3px border of object
for d in range(3):
    for side in (100 + d, 199 - d):
        a[side, 100:200, :3] = [120, 180, 60]  # greenish edge
        a[100:200, side, :3] = [120, 180, 60]
im = Image.fromarray(a, "RGBA")
r = remove_background(im, BackgroundConfig(mode="auto"))
print(f"\ngreen-spill object: detect={r.detected_mode} transp={transp_frac(r.image):.1%}")
for bg, name in [((0, 0, 0), "black"), ((255, 255, 255), "white")]:
    comp = composite_on(r.image, bg)
    edge = comp[100, 100:200].mean(axis=0)
    interior = comp[150, 150]
    print(f"  on {name}: object-edge RGB={edge.round(0)} interior RGB={interior}")

print("\nDONE")
