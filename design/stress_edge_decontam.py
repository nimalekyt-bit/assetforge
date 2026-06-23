"""Adversarial edge-quality / decontamination stress tests for AssetForge.

Theme: _decontaminate_edge, soft/feather край, despill.
We composite results on BLACK, WHITE and MAGENTA backgrounds and numerically
hunt for light/dark halos along the edge. Break on: soft shadows/glow
(semi-transparent must survive); thin lines; glass/translucent; antialias on a
contrasting edge; chroma despill that grays legit green.

Engine is read-only. We only measure.
"""
from __future__ import annotations

import sys
import time
import numpy as np
from PIL import Image

sys.path.insert(0, r"E:\photovirez")

from assetforge.core.background import remove_background, detect_background
from assetforge.core.config import BackgroundConfig


# ---------------------------------------------------------------- utilities

def composite_on(rgba: Image.Image, bg_rgb) -> np.ndarray:
    """Alpha-composite RGBA image over a flat bg color. Returns float32 RGB HxWx3."""
    a = np.asarray(rgba.convert("RGBA")).astype(np.float32)
    rgb = a[:, :, :3]
    alpha = a[:, :, 3:4] / 255.0
    bg = np.array(bg_rgb, dtype=np.float32)[None, None, :]
    return rgb * alpha + bg * (1.0 - alpha)


def alpha_of(rgba: Image.Image) -> np.ndarray:
    return np.asarray(rgba.convert("RGBA")).astype(np.float32)[:, :, 3]


def transparent_frac(rgba: Image.Image) -> float:
    a = alpha_of(rgba)
    return float((a < 16).mean())


def edge_band_mask(alpha: np.ndarray, lo=8, hi=247) -> np.ndarray:
    """Pixels on the soft edge (partially transparent)."""
    return (alpha > lo) & (alpha < hi)


def section(name):
    print("\n" + "=" * 72)
    print(name)
    print("=" * 72)


# ---------------------------------------------------------------- builders

def make_solid_circle_on_white(size=200, radius=70, fill=(40, 90, 200)):
    """Antialiased solid disk on white. Classic 'remove white bg' case."""
    SS = 4
    big = Image.new("RGB", (size * SS, size * SS), (255, 255, 255))
    arr = np.asarray(big).astype(np.float32).copy()
    yy, xx = np.mgrid[0:size * SS, 0:size * SS]
    cx = cy = size * SS / 2
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    inside = d <= radius * SS
    arr[inside] = np.array(fill, dtype=np.float32)
    img = Image.fromarray(arr.astype(np.uint8)).resize((size, size), Image.LANCZOS)
    return img


def make_translucent_glow(size=200, fill=(220, 60, 60), max_alpha=140):
    """A soft radial glow: genuinely semi-transparent object on WHITE.
    Must survive bg removal (NOT be eaten)."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    cx = cy = size / 2
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    r = size * 0.42
    a = np.clip(1.0 - d / r, 0.0, 1.0) ** 1.5 * (max_alpha / 255.0)  # 0..max_alpha
    # composite this glow over white to make an opaque RGB input (no alpha channel)
    fillv = np.array(fill, dtype=np.float32)[None, None, :]
    white = np.array([255, 255, 255], dtype=np.float32)[None, None, :]
    a3 = a[:, :, None]
    rgb = fillv * a3 + white * (1.0 - a3)
    return Image.fromarray(rgb.astype(np.uint8), "RGB"), a  # also return ground-truth alpha


def make_thin_lines_on_white(size=200, fill=(20, 20, 20)):
    SS = 4
    big = Image.new("RGB", (size * SS, size * SS), (255, 255, 255))
    arr = np.asarray(big).astype(np.float32).copy()
    for i in range(1, 8):
        x = int(i * size * SS / 8)
        w = max(1, i)  # increasing widths
        arr[:, x:x + w] = np.array(fill, dtype=np.float32)
    img = Image.fromarray(arr.astype(np.uint8)).resize((size, size), Image.LANCZOS)
    return img


def make_green_screen(size=200, obj_fill=(40, 200, 40), bg=(20, 200, 30), radius=60):
    """A GREEN object on a GREEN screen. Despill must not gray the legit green object."""
    arr = np.zeros((size, size, 3), dtype=np.float32)
    arr[:, :] = np.array(bg, dtype=np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    cx = cy = size / 2
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    inside = d <= radius
    arr[inside] = np.array(obj_fill, dtype=np.float32)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def make_green_screen_aa(size=200, obj_fill=(40, 200, 40), bg=(20, 200, 30), radius=60):
    SS = 4
    arr = np.zeros((size * SS, size * SS, 3), dtype=np.float32)
    arr[:, :] = np.array(bg, dtype=np.float32)
    yy, xx = np.mgrid[0:size * SS, 0:size * SS]
    cx = cy = size * SS / 2
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    arr[d <= radius * SS] = np.array(obj_fill, dtype=np.float32)
    return Image.fromarray(arr.astype(np.uint8)).resize((size, size), Image.LANCZOS)


def make_white_obj_on_green(size=200, radius=60, bg=(20, 200, 30)):
    """White/neutral object on green screen — green spill onto white edges is the
    classic despill case. After despill should look white, not magenta/gray."""
    SS = 4
    arr = np.zeros((size * SS, size * SS, 3), dtype=np.float32)
    arr[:, :] = np.array(bg, dtype=np.float32)
    yy, xx = np.mgrid[0:size * SS, 0:size * SS]
    cx = cy = size * SS / 2
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    arr[d <= radius * SS] = np.array([240, 240, 240], dtype=np.float32)
    return Image.fromarray(arr.astype(np.uint8)).resize((size, size), Image.LANCZOS)


def make_dark_obj_on_white(size=200, radius=70, fill=(10, 10, 10)):
    """Dark disk on white. Decontamination of a dark edge against bright bg."""
    return make_solid_circle_on_white(size, radius, fill)


# ---------------------------------------------------------------- metrics

def halo_report(rgba: Image.Image, gt_inside=None, label=""):
    """Composite on black/white/magenta, measure brightness deltas vs expected fill
    along the edge band. Returns dict of metrics."""
    alpha = alpha_of(rgba)
    edge = edge_band_mask(alpha)
    n_edge = int(edge.sum())
    res = {"label": label, "n_edge": n_edge}
    if n_edge == 0:
        return res
    on_black = composite_on(rgba, (0, 0, 0))
    on_white = composite_on(rgba, (255, 255, 255))
    on_mag = composite_on(rgba, (255, 0, 255))
    # For a correct premultiplied edge, compositing on black vs white the *object*
    # color contribution scales with alpha; difference between black/white comp at
    # edge reveals residual bg energy that shouldn't be there.
    # Light halo on black = edge pixels appearing brighter than the object on black.
    res["edge_mean_black"] = on_black[edge].mean(axis=0).round(1).tolist()
    res["edge_mean_white"] = on_white[edge].mean(axis=0).round(1).tolist()
    res["edge_mean_mag"] = on_mag[edge].mean(axis=0).round(1).tolist()
    return res


def color_fringe_score(rgba: Image.Image, expected_neutral=True):
    """On a magenta bg, measure how much magenta (R&B high, G low) leaks into edge."""
    alpha = alpha_of(rgba)
    edge = edge_band_mask(alpha)
    if edge.sum() == 0:
        return None
    rgb = np.asarray(rgba.convert("RGBA")).astype(np.float32)[:, :, :3]
    e = rgb[edge]
    # magenta-ness of the *stored* (un-premultiplied) edge color
    mag = (e[:, 0] + e[:, 2]) / 2 - e[:, 1]
    return float(mag.mean()), float(mag.max())


# ================================================================ TESTS

def test_white_circle_halo():
    section("TEST 1: Solid AA disk on WHITE -> halo on black/white/magenta")
    img = make_solid_circle_on_white(fill=(40, 90, 200))
    mode, info = detect_background(np.asarray(img.convert("RGBA")).astype(np.float32))
    print(f"detect_background -> {mode} ({info})")
    res = remove_background(img, BackgroundConfig(mode="auto"))
    print("detected_mode:", res.detected_mode, "notes:", res.notes)
    print("transparent_frac:", round(transparent_frac(res.image), 3))
    rep = halo_report(res.image, label="white_circle")
    print("edge n:", rep["n_edge"])
    print("edge composite on BLACK rgb:", rep.get("edge_mean_black"))
    print("edge composite on WHITE rgb:", rep.get("edge_mean_white"))
    print("edge composite on MAGENTA rgb:", rep.get("edge_mean_mag"))
    # object is blue (40,90,200). On black, a clean edge should be a dim blue.
    # A WHITE halo => edge much brighter / whiter than object.
    eb = np.array(rep.get("edge_mean_black", [0, 0, 0]))
    print(">> light-halo indicator (edge brightness on black, lower=cleaner):",
          round(float(eb.mean()), 1))
    return res


def test_translucent_glow_survival():
    section("TEST 2: Translucent glow on WHITE -> must SURVIVE (not eaten)")
    img, gt_alpha = make_translucent_glow(fill=(220, 60, 60), max_alpha=140)
    arrf = np.asarray(img.convert("RGBA")).astype(np.float32)
    mode, info = detect_background(arrf)
    print(f"detect_background -> {mode} ({info})")
    res = remove_background(img, BackgroundConfig(mode="auto"))
    print("detected_mode:", res.detected_mode, "notes:", res.notes)
    out_a = alpha_of(res.image) / 255.0
    gt = gt_alpha  # 0..~0.55
    # center: glow at peak ~max_alpha. Did it survive?
    cx = cy = img.size[0] // 2
    print(f"GT center alpha: {gt[cy, cx]:.3f}  OUT center alpha: {out_a[cy, cx]:.3f}")
    print(f"GT mean (where gt>0.05): {gt[gt > 0.05].mean():.3f}")
    survived = float((out_a > 0.05).sum())
    expected = float((gt > 0.05).sum())
    print(f"px with alpha>0.05  GT={expected:.0f}  OUT={survived:.0f}  "
          f"survival_ratio={survived / max(expected,1):.3f}")
    # Try explicit white mode too
    res2 = remove_background(img, BackgroundConfig(mode="white"))
    out_a2 = alpha_of(res2.image) / 255.0
    print(f"[white mode] center alpha: {out_a2[cy, cx]:.3f}  "
          f"px>0.05={float((out_a2>0.05).sum()):.0f}")
    return res, gt_alpha


def test_thin_lines():
    section("TEST 3: Thin dark lines on WHITE -> survival + halo")
    img = make_thin_lines_on_white()
    res = remove_background(img, BackgroundConfig(mode="auto"))
    print("detected_mode:", res.detected_mode, "notes:", res.notes)
    out_a = alpha_of(res.image)
    # how much of the line ink survived (the 1px lines especially)
    print("max alpha:", float(out_a.max()), "mean opaque frac:",
          round(float((out_a > 200).mean()), 4))
    rep = halo_report(res.image, label="thin_lines")
    print("edge composite on BLACK rgb:", rep.get("edge_mean_black"))
    print("edge composite on WHITE rgb:", rep.get("edge_mean_white"))
    return res


def test_green_obj_on_green():
    section("TEST 4: GREEN object on GREEN screen -> despill must not gray legit green")
    img = make_green_screen_aa(obj_fill=(40, 200, 40), bg=(20, 200, 30))
    mode, info = detect_background(np.asarray(img.convert("RGBA")).astype(np.float32))
    print(f"detect_background -> {mode} ({info})")
    # ground truth object green
    res = remove_background(img, BackgroundConfig(mode="auto"))
    print("detected_mode:", res.detected_mode, "notes:", res.notes)
    rgb = np.asarray(res.image.convert("RGBA")).astype(np.float32)
    a = rgb[:, :, 3]
    core = a > 250
    if core.any():
        mean_core = rgb[:, :, :3][core].mean(axis=0)
        print("object core color (should stay ~(40,200,40)):", mean_core.round(1).tolist())
        g_loss = 200 - mean_core[1]
        print(">> green channel loss in core (0=perfect):", round(float(g_loss), 1))
    else:
        print("!! object core fully removed (eaten)! opaque frac:",
              round(float(core.mean()), 4))
    print("transparent_frac:", round(transparent_frac(res.image), 3))
    return res


def test_white_obj_on_green_despill():
    section("TEST 5: WHITE object on GREEN -> green spill removal on edge")
    img = make_white_obj_on_green()
    res = remove_background(img, BackgroundConfig(mode="auto"))
    print("detected_mode:", res.detected_mode, "notes:", res.notes)
    rgb = np.asarray(res.image.convert("RGBA")).astype(np.float32)
    a = rgb[:, :, 3]
    edge = edge_band_mask(a)
    if edge.any():
        em = rgb[:, :, :3][edge]
        green_excess = em[:, 1] - (em[:, 0] + em[:, 2]) / 2
        print("edge green excess (g - (r+b)/2), should be ~0 after despill:",
              round(float(green_excess.mean()), 1), "max:", round(float(green_excess.max()), 1))
    # composite on magenta to expose any leftover green fringe / dark fringe
    rep = halo_report(res.image, label="white_on_green")
    print("edge composite on MAGENTA rgb:", rep.get("edge_mean_mag"))
    print("edge composite on BLACK rgb:", rep.get("edge_mean_black"))
    return res


def test_decontam_low_alpha_amplification():
    section("TEST 6: low-alpha decontamination -> noise amplification / overshoot")
    # gradient edge: a blue-ish object fading into colored solid bg.
    size = 160
    bg = (200, 40, 40)  # red solid bg
    obj = (30, 60, 220)
    arr = np.zeros((size, size, 3), dtype=np.float32)
    arr[:, :] = bg
    # horizontal alpha ramp object band in the middle, with a smooth transition
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    band = (xx > 40) & (xx < 120)
    # smooth transition over a few px on each side
    t = np.clip((xx - 40) / 20.0, 0, 1) * np.clip((120 - xx) / 20.0, 0, 1)
    a3 = t[:, :, None]
    rgb = np.array(obj, dtype=np.float32)[None, None, :] * a3 + np.array(bg, dtype=np.float32)[None, None, :] * (1 - a3)
    img = Image.fromarray(rgb.astype(np.uint8), "RGB")
    res = remove_background(img, BackgroundConfig(mode="solid"))
    print("detected_mode:", res.detected_mode, "notes:", res.notes)
    out = np.asarray(res.image.convert("RGBA")).astype(np.float32)
    a = out[:, :, 3]
    rgbo = out[:, :, :3]
    edge = edge_band_mask(a)
    if edge.any():
        # check for overshoot: object RGB pushed to extremes (0 or 255) on low alpha
        low = edge & (a < 60)
        if low.any():
            lv = rgbo[low]
            clipped = ((lv <= 0.5) | (lv >= 254.5)).any(axis=1)
            print(f"low-alpha edge px (a<60): {int(low.sum())}, "
                  f"fraction clamped to 0/255: {float(clipped.mean()):.3f}")
            print("low-alpha edge RGB mean:", lv.mean(axis=0).round(1).tolist(),
                  "std:", lv.std(axis=0).round(1).tolist())
    # composite back on the ORIGINAL bg color: a correct decontam should reproduce
    # the band cleanly; halo = brightness mismatch
    comp = composite_on(res.image, bg)
    # the bg region should equal bg exactly (alpha 0). Edge halo = deviation.
    bg_region = ~band
    dev = np.abs(comp[bg_region] - np.array(bg, dtype=np.float32)).mean()
    print("mean deviation in bg region after re-composite on bg (should be ~0):",
          round(float(dev), 2))
    return res


def test_perf_large():
    section("TEST 7: performance / memory on large image")
    import tracemalloc
    size = 3000
    img = make_green_screen_aa(size=size, radius=900)
    tracemalloc.start()
    t0 = time.time()
    res = remove_background(img, BackgroundConfig(mode="auto"))
    dt = time.time() - t0
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"{size}x{size} chroma auto: {dt:.2f}s, peak {peak/1e6:.0f} MB, mode={res.detected_mode}")
    # also non-chroma solid which builds (H,W,k,3) distance tensor
    img2 = make_solid_circle_on_white(size=size, radius=900)
    tracemalloc.start()
    t0 = time.time()
    res2 = remove_background(img2, BackgroundConfig(mode="solid"))
    dt2 = time.time() - t0
    cur, peak2 = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"{size}x{size} solid: {dt2:.2f}s, peak {peak2/1e6:.0f} MB, mode={res2.detected_mode}")
    return res


def test_checker_decontam():
    section("TEST 8: object over checkerboard transparency-bg + soft edge")
    size = 200
    # checkerboard light/gray
    arr = np.zeros((size, size, 3), dtype=np.float32)
    cs = 16
    for y in range(0, size, cs):
        for x in range(0, size, cs):
            c = 255 if ((x // cs + y // cs) % 2 == 0) else 200
            arr[y:y+cs, x:x+cs] = c
    # AA blue disk on top
    SS = 1
    yy, xx = np.mgrid[0:size, 0:size]
    cx = cy = size / 2
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    t = np.clip((60 - d) / 2.0, 0, 1)[:, :, None]
    obj = np.array([200, 50, 50], dtype=np.float32)[None, None, :]
    arr = obj * t + arr * (1 - t)
    img = Image.fromarray(arr.astype(np.uint8), "RGB")
    res = remove_background(img, BackgroundConfig(mode="auto"))
    print("detected_mode:", res.detected_mode, "notes:", res.notes)
    print("transparent_frac:", round(transparent_frac(res.image), 3))
    rep = halo_report(res.image, label="checker")
    print("edge composite on BLACK rgb:", rep.get("edge_mean_black"))
    print("edge composite on WHITE rgb:", rep.get("edge_mean_white"))
    return res


if __name__ == "__main__":
    test_white_circle_halo()
    test_translucent_glow_survival()
    test_thin_lines()
    test_green_obj_on_green()
    test_white_obj_on_green_despill()
    test_decontam_low_alpha_amplification()
    test_perf_large()
    test_checker_decontam()
    print("\nDONE")
