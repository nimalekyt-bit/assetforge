"""Adversarial stress test for background detection/removal.

Theme: detect_background / _color_key / checker / _detect_neutral_tones.
We synthesize images (PIL) and measure:
  - detected_mode
  - transparent fraction after removal (alpha<16)
  - alpha in 4 corners (background, expect 0)
  - alpha in center (object, expect 255)
  - halo on composite over dark/colored bg
"""
from __future__ import annotations

import time
import numpy as np
from PIL import Image, ImageDraw

from assetforge.core.background import remove_background, detect_background
from assetforge.core.config import BackgroundConfig


def stats(res_img: Image.Image, obj_center_expected=True):
    a = np.asarray(res_img.convert("RGBA"))[:, :, 3]
    h, w = a.shape
    transp = float((a < 16).mean())
    corners = [int(a[2, 2]), int(a[2, w - 3]), int(a[h - 3, 2]), int(a[h - 3, w - 3])]
    cy, cx = h // 2, w // 2
    center = int(a[cy, cx])
    # center region mean (avoid single-pixel noise)
    cregion = a[cy - max(1, h // 20):cy + max(1, h // 20), cx - max(1, w // 20):cx + max(1, w // 20)]
    center_mean = float(cregion.mean())
    return dict(transp=transp, corners=corners, center=center, center_mean=center_mean)


def run_case(name, img, cfg=None, expected_mode=None):
    cfg = cfg or BackgroundConfig(mode="auto")
    t0 = time.time()
    res = remove_background(img, cfg)
    dt = (time.time() - t0) * 1000
    s = stats(res.image)
    print(f"\n=== {name} ===")
    print(f"  detected_mode = {res.detected_mode}  (expected ~ {expected_mode})")
    print(f"  notes        = {res.notes}")
    print(f"  transp_frac  = {s['transp']:.3f}")
    print(f"  corners alpha= {s['corners']}  (bg -> expect ~0)")
    print(f"  center alpha = {s['center']}  center_mean={s['center_mean']:.0f}  (obj -> expect ~255)")
    print(f"  time         = {dt:.0f} ms")
    return res, s


def make_checker(w, h, c1, c2, cell, draw_obj=True, obj_color=(200, 30, 30)):
    img = Image.new("RGBA", (w, h), (*c1, 255))
    d = ImageDraw.Draw(img)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            if ((x // cell) + (y // cell)) % 2 == 0:
                d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(*c2, 255))
    if draw_obj:
        d.ellipse([w // 4, h // 4, 3 * w // 4, 3 * h // 4], fill=(*obj_color, 255))
    return img


def make_solid(w, h, bg, obj=(200, 30, 30), draw=True):
    img = Image.new("RGBA", (w, h), (*bg, 255))
    if draw:
        d = ImageDraw.Draw(img)
        d.ellipse([w // 4, h // 4, 3 * w // 4, 3 * h // 4], fill=(*obj, 255))
    return img


def make_gradient(w, h, c_top, c_bot, obj=(200, 30, 30)):
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(h):
        t = y / max(1, h - 1)
        arr[y, :, 0] = int(c_top[0] * (1 - t) + c_bot[0] * t)
        arr[y, :, 1] = int(c_top[1] * (1 - t) + c_bot[1] * t)
        arr[y, :, 2] = int(c_top[2] * (1 - t) + c_bot[2] * t)
        arr[y, :, 3] = 255
    img = Image.fromarray(arr, "RGBA")
    d = ImageDraw.Draw(img)
    d.ellipse([w // 4, h // 4, 3 * w // 4, 3 * h // 4], fill=(*obj, 255))
    return img


def halo_check(res_img, bg_rgb):
    """Composite over solid bg, measure mean residual brightness in corners
    (halo = leftover bg color bleeding)."""
    im = res_img.convert("RGBA")
    bg = Image.new("RGBA", im.size, (*bg_rgb, 255))
    comp = Image.alpha_composite(bg, im)
    a = np.asarray(comp)[:, :, :3].astype(np.int32)
    base = np.array(bg_rgb)
    diff = np.abs(a - base).sum(axis=2)
    h, w = diff.shape
    # ring region (between border and object) - sample mid edges
    border = np.concatenate([
        diff[:h // 8, :].ravel(), diff[-h // 8:, :].ravel(),
        diff[:, :w // 8].ravel(), diff[:, -w // 8:].ravel(),
    ])
    return float(border.mean()), int(border.max())


W = H = 256

print("#" * 70)
print("# CHECKERBOARDS")
print("#" * 70)

# Light checker (classic transparency)
run_case("checker light (240/255, cell 16)", make_checker(W, H, (255, 255, 255), (204, 204, 204), 16), expected_mode="checker")
# Dark-grey checker
run_case("checker DARK grey (60/90, cell 16)", make_checker(W, H, (60, 60, 60), (90, 90, 90), 16), expected_mode="checker?")
# Very dark checker
run_case("checker VERY DARK (30/55, cell 16)", make_checker(W, H, (30, 30, 30), (55, 55, 55), 16), expected_mode="checker?")
# Colored checker (cyan/magenta-ish but low sat?) - use colored tiles
run_case("checker COLORED (blue/lightblue)", make_checker(W, H, (40, 80, 200), (120, 160, 240), 16), expected_mode="?")
# Large cells - so a corner may be entirely one cell
run_case("checker BIG cells (cell 64)", make_checker(W, H, (255, 255, 255), (204, 204, 204), 64), expected_mode="checker")
# Huge cells - border frac 0.06 = ~15px, smaller than cell -> each border edge may be single tone
run_case("checker HUGE cells (cell 128)", make_checker(W, H, (255, 255, 255), (204, 204, 204), 128), expected_mode="checker?")
# Asymmetric tones (one very light, one mid)
run_case("checker wide-contrast (255/128)", make_checker(W, H, (255, 255, 255), (128, 128, 128), 16), expected_mode="checker")

print("\n" + "#" * 70)
print("# SOLID / WHITE")
print("#" * 70)

run_case("white bg (255)", make_solid(W, H, (255, 255, 255)), expected_mode="white")
run_case("near-white bg (248)", make_solid(W, H, (248, 248, 248)), expected_mode="white")
run_case("solid grey bg (128)", make_solid(W, H, (128, 128, 128)), expected_mode="solid")
run_case("solid colored bg (orange)", make_solid(W, H, (230, 150, 40)), expected_mode="solid")
run_case("solid red bg (red obj on red-ish)", make_solid(W, H, (200, 40, 40), obj=(40, 40, 200)), expected_mode="solid")

print("\n" + "#" * 70)
print("# CHROMA")
print("#" * 70)
run_case("green screen", make_solid(W, H, (20, 200, 30), obj=(200, 180, 150)), expected_mode="chroma")
run_case("blue screen", make_solid(W, H, (30, 40, 200), obj=(200, 180, 150)), expected_mode="chroma")
# Green object on green screen (despill risk)
run_case("green obj on green screen", make_solid(W, H, (20, 200, 30), obj=(40, 160, 60)), expected_mode="chroma")

print("\n" + "#" * 70)
print("# GRADIENT")
print("#" * 70)
run_case("vertical gradient grey", make_gradient(W, H, (230, 230, 230), (170, 170, 170)), expected_mode="?")
run_case("vertical gradient white->grey subtle", make_gradient(W, H, (250, 250, 250), (220, 220, 220)), expected_mode="white?")
run_case("vertical gradient colored sky", make_gradient(W, H, (135, 206, 235), (255, 255, 255)), expected_mode="?")

print("\n" + "#" * 70)
print("# LIGHT OBJECT ON WHITE (background ~ object)")
print("#" * 70)
# light grey object on white
run_case("light-grey obj (235) on white", make_solid(W, H, (255, 255, 255), obj=(235, 235, 235)), expected_mode="white")
# near-white object on white
run_case("near-white obj (250) on white", make_solid(W, H, (255, 255, 255), obj=(250, 250, 250)), expected_mode="white/none?")

print("\n" + "#" * 70)
print("# ALREADY-TRANSPARENT PNG")
print("#" * 70)
# transparent png with object
tp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(tp)
d.ellipse([W // 4, H // 4, 3 * W // 4, 3 * H // 4], fill=(200, 30, 30, 255))
run_case("transparent png + opaque obj", tp, expected_mode="alpha")
# semi-transparent edges (anti-aliased) png
tp2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(tp2)
for r in range(40, 0, -1):
    aa = int(255 * (r / 40))
    d.ellipse([W // 4 - r, H // 4 - r, 3 * W // 4 + r, 3 * H // 4 + r], outline=(200, 30, 30, aa))
d.ellipse([W // 4, H // 4, 3 * W // 4, 3 * H // 4], fill=(200, 30, 30, 255))
run_case("transparent png + soft edge obj", tp2, expected_mode="alpha")

print("\n" + "#" * 70)
print("# PHOTO BACKGROUND (textured)")
print("#" * 70)
rng = np.random.default_rng(0)
photo = rng.integers(80, 180, size=(H, W, 3), dtype=np.uint8)
pimg = np.dstack([photo, np.full((H, W), 255, np.uint8)]).astype(np.uint8)
pim = Image.fromarray(pimg, "RGBA")
d = ImageDraw.Draw(pim)
d.ellipse([W // 4, H // 4, 3 * W // 4, 3 * H // 4], fill=(200, 30, 30, 255))
run_case("noisy photo bg", pim, expected_mode="none")

print("\n" + "#" * 70)
print("# HALO ON DARK COMPOSITE (white bg removal quality)")
print("#" * 70)
res, _ = run_case("white bg for halo test", make_solid(W, H, (255, 255, 255), obj=(30, 30, 200)), expected_mode="white")
mean_h, max_h = halo_check(res.image, (0, 0, 0))
print(f"  HALO over black: mean_diff={mean_h:.1f} max_diff={max_h}")

res2, _ = run_case("dark checker for halo test", make_checker(W, H, (60, 60, 60), (90, 90, 90), 16, obj_color=(220, 220, 50)), expected_mode="checker?")
mean_h2, max_h2 = halo_check(res2.image, (255, 0, 0))
print(f"  HALO over red: mean_diff={mean_h2:.1f} max_diff={max_h2}")
