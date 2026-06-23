# -*- coding: utf-8 -*-
"""Adversarial stress test for CROP + EXPORT path of AssetForge.

Focus: fit=contain/width/none + square; PNG vs ICO/ICNS positioning;
non-proportional crop stretching; sharpness of small sizes (16/24/32);
padding; contact-sheet; non-square logos.
"""
from __future__ import annotations
import io, sys, math
import numpy as np
from PIL import Image

sys.path.insert(0, r"E:\photovirez")

from assetforge.core.config import (CropConfig, ResizeConfig, ExportConfig,
                                     ICO_SIZES, ICNS_SIZES)
from assetforge.core import crop as crop_mod
from assetforge.core import resize as resize_mod
from assetforge.core import export as export_mod
from assetforge.core import io_utils, detect


def banner(s):
    print("\n" + "=" * 70)
    print(s)
    print("=" * 70)


def alpha_np(im):
    return np.asarray(im.convert("RGBA"))[:, :, 3]


def alpha_centroid(im):
    """Centroid (cx, cy) of alpha mass, normalized to [0,1]."""
    a = alpha_np(im).astype(np.float64)
    tot = a.sum()
    if tot == 0:
        return None
    h, w = a.shape
    ys, xs = np.mgrid[0:h, 0:w]
    cx = (a * xs).sum() / tot / max(1, w - 1)
    cy = (a * ys).sum() / tot / max(1, h - 1)
    return cx, cy


def content_bbox_norm(im):
    """Content bbox normalized to [0,1] within the image."""
    bb = im.getbbox()
    if bb is None:
        return None
    w, h = im.size
    return (bb[0] / w, bb[1] / h, bb[2] / w, bb[3] / h)


# --------- build synthetic test images ---------

def make_wide_logo(W=600, H=120, bg=(0, 0, 0, 0)):
    """A wide 'wordmark' style logo: 5:1 aspect, opaque colored bar with a notch."""
    im = Image.new("RGBA", (W, H), bg)
    px = im.load()
    for y in range(H):
        for x in range(W):
            # gradient bar, leave a triangular notch top-left to detect flips/stretch
            inside = (10 <= x <= W - 10 and 10 <= y <= H - 10)
            if inside:
                px[x, y] = (40 + (x * 200 // W), 80, 200 - (x * 150 // W), 255)
    # asymmetric marker: a solid red square near LEFT edge so we can see position
    for y in range(20, 50):
        for x in range(20, 50):
            px[x, y] = (255, 0, 0, 255)
    return im


def make_tall_logo(W=120, H=600):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = im.load()
    for y in range(10, H - 10):
        for x in range(10, W - 10):
            px[x, y] = (50, 160, 90, 255)
    for y in range(20, 50):
        for x in range(20, 50):
            px[x, y] = (255, 0, 0, 255)
    return im


def make_fine_detail_square(S=512):
    """Square with thin 1px lines / fine checker to test sharpness at 16/24/32."""
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    a = np.zeros((S, S, 4), np.uint8)
    # opaque base disk
    yy, xx = np.mgrid[0:S, 0:S]
    r = math.hypot(S / 2, S / 2)
    disk = ((xx - S / 2) ** 2 + (yy - S / 2) ** 2) <= (S * 0.46) ** 2
    a[disk] = (30, 60, 120, 255)
    # fine concentric rings + radial spokes (high frequency -> tests anti-alias/sharpen)
    rad = np.hypot(xx - S / 2, yy - S / 2)
    rings = (np.sin(rad / 4.0) > 0.6) & disk
    a[rings] = (240, 240, 250, 255)
    return Image.fromarray(a, "RGBA")


def make_small_object_on_big_canvas(canvas=1000, obj=80):
    """A small opaque object near top-left of a big transparent canvas.
    Tests: does padding/positioning center it? does small detail stay sharp?"""
    im = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    px = im.load()
    x0, y0 = 60, 60
    for y in range(y0, y0 + obj):
        for x in range(x0, x0 + obj):
            px[x, y] = (200, 40, 40, 255)
    # tiny 1px white frame
    for x in range(x0, x0 + obj):
        px[x, y0] = (255, 255, 255, 255)
        px[x, y0 + obj - 1] = (255, 255, 255, 255)
    return im


# =====================================================================
banner("TEST 1: fit=contain vs fit=none vs fit=width on a WIDE 5:1 logo")
wide = make_wide_logo()
print("source size:", wide.size, "bbox:", wide.getbbox())
bb = detect.content_bbox(wide, threshold=16)
print("content bbox:", bb, "-> aspect", round((bb[2]-bb[0])/(bb[3]-bb[1]),3))

for fitname in ("contain", "none", "width"):
    cfg = CropConfig(fit=fitname, square=True, padding_pct=0.0, align="center")
    out = crop_mod.apply_crop(wide, bb, cfg)
    print(f"  apply_crop fit={fitname:8s} square=True -> out {out.size}  "
          f"square_canvas={out.size[0]==out.size[1]}")

# Now full resize step for each, to a small size and check aspect preservation
banner("TEST 1b: does fit=none stretch? Compare object aspect after resize_to")
rcfg = ResizeConfig()
for fitname in ("contain", "none", "width"):
    cfg = CropConfig(fit=fitname, square=(fitname != "width"), padding_pct=0.0)
    out = crop_mod.apply_crop(wide, bb, cfg)
    sq = cfg.square and cfg.fit != "width"
    r = resize_mod.resize_to(out, 256, rcfg, square=sq)
    # measure aspect of the red marker block to detect stretch
    arr = np.asarray(r)
    red = (arr[:, :, 0] > 180) & (arr[:, :, 1] < 80) & (arr[:, :, 2] < 80) & (arr[:, :, 3] > 128)
    ys, xs = np.where(red)
    if len(xs):
        aspect = (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)
    else:
        aspect = None
    print(f"  fit={fitname:8s} square_arg={sq} resized={r.size} red-marker aspect={aspect} (orig=1.0 square)")


# =====================================================================
banner("TEST 2: PNG vs ICO vs ICNS positioning for the SAME source")
# Use icon-set-like config
fine = make_fine_detail_square(512)
bb2 = detect.content_bbox(fine, threshold=16)
cfg = CropConfig(fit="contain", square=True, padding_pct=6.0, align="center")
cropped = crop_mod.apply_crop(fine, bb2, cfg)
print("cropped (square) size:", cropped.size)

rcfg = ResizeConfig()
ecfg = ExportConfig(sizes=[16, 32, 48, 64, 128, 256, 512],
                    formats=["png", "ico", "icns"], make_contact_sheet=True)
res = export_mod.build_export(cropped, ecfg, rcfg, square=True,
                              meta={"preset": "icon-set", "bg_mode": "auto", "objects": 1})

# Extract a PNG and the ICO, compare centroid at 64px
png64 = None
for a in res.by_kind("png"):
    if a.name.endswith("_64.png"):
        png64 = Image.open(io.BytesIO(a.data)).convert("RGBA")
ico = res.by_kind("ico")[0]
ico_img = Image.open(io.BytesIO(ico.data))
print("ICO contains sizes:", ico_img.info.get("sizes"))

# Pillow ICO: load each frame
ico_frames = {}
try:
    for sz in sorted(ico_img.info.get("sizes", [])):
        fr = Image.open(io.BytesIO(ico.data))
        fr.size = sz  # request that size
        fr.load()
        ico_frames[sz[0]] = fr.convert("RGBA")
except Exception as e:
    print("ico frame load err:", e)

cpng = alpha_centroid(png64)
print("PNG 64 centroid:", tuple(round(v,4) for v in cpng))
if 64 in ico_frames:
    cico = alpha_centroid(ico_frames[64])
    print("ICO 64 centroid:", tuple(round(v,4) for v in cico))
    print("centroid delta (px@64):", round(abs(cpng[0]-cico[0])*64,3), round(abs(cpng[1]-cico[1])*64,3))


# =====================================================================
banner("TEST 3: sharpness of small sizes 16/24/32 (mid-freq energy)")
def hf_energy(im):
    """High-frequency energy via Laplacian variance on luminance*alpha."""
    arr = np.asarray(im.convert("RGBA")).astype(np.float64)
    lum = (0.299*arr[:,:,0] + 0.587*arr[:,:,1] + 0.114*arr[:,:,2]) * (arr[:,:,3]/255.0)
    lap = (lum[:-2,1:-1] + lum[2:,1:-1] + lum[1:-1,:-2] + lum[1:-1,2:] - 4*lum[1:-1,1:-1])
    return float(lap.var())

# compare unsharp ON vs OFF at small sizes
for size in (16, 24, 32, 48):
    on = resize_mod.resize_to(cropped, size, ResizeConfig(unsharp=True), square=True)
    off = resize_mod.resize_to(cropped, size, ResizeConfig(unsharp=False), square=True)
    # also a naive direct lanczos for reference (no letterbox bias)
    print(f"  size {size:3d}: HF unsharp_on={hf_energy(on):.2f}  off={hf_energy(off):.2f}  "
          f"ratio={hf_energy(on)/max(1e-9,hf_energy(off)):.3f}")

# Check the unsharp trigger condition for a SMALL object letterboxed in big canvas
banner("TEST 3b: unsharp trigger with letterbox-inflated dims")
small = make_small_object_on_big_canvas(1000, 80)
bb3 = detect.content_bbox(small, threshold=16)
print("tiny object bbox:", bb3, "(80x80-ish)")
cfg3 = CropConfig(fit="contain", square=True, padding_pct=6.0)
crop3 = crop_mod.apply_crop(small, bb3, cfg3)
print("cropped object size:", crop3.size)
# In resize_to, the trigger uses w,h of the INPUT (crop3). max(w,h)>size*1.5 ?
for size in (16, 32, 64):
    w, h = crop3.size
    trig = (size <= 96 and max(w, h) > size * 1.5)
    print(f"  size {size}: input {w}x{h} -> unsharp triggers? {trig}")


# =====================================================================
banner("TEST 4: padding correctness (% of max bbox side)")
# object 80px, padding 6% -> pad = round(80*6/100)=5 px each side
pad = round(80 * 6 / 100)
print("expected pad px:", pad)
bb_obj = (60, 60, 140, 140)  # 80x80
c = crop_mod.crop_to_bbox(small, bb_obj, 6.0)
print("crop_to_bbox size:", c.size, "(expect", (80+2*pad), "x", (80+2*pad), ")")


# =====================================================================
banner("TEST 5: non-square wide logo via fit=width path (wordmark)")
cfgw = CropConfig(fit="width", square=False, padding_pct=0.0)
outw = crop_mod.apply_crop(wide, bb, cfgw)
print("apply_crop fit=width out size:", outw.size, "(should keep wide aspect, NOT square)")
rw = resize_mod.resize_to(outw, 512, ResizeConfig(), square=False)
print("resize square=False to width 512 ->", rw.size, "(height should be ~512*H/W)")
# Now what if user picks web-logo preset but with ICO format requested?
ecfgw = ExportConfig(sizes=[256, 512, 1024], formats=["png", "ico", "icns"], make_contact_sheet=False)
resw = export_mod.build_export(outw, ecfgw, ResizeConfig(), square=False)
print("web-logo build_export with ico/icns requested, square=False -> kinds:",
      sorted(set(a.kind for a in resw.artifacts)))
print("  (ICO/ICNS skipped because guarded by 'and square'? )")


# =====================================================================
banner("TEST 6: ICO/ICNS upscaling of a SMALL crop -> blur?")
# small object cropped is ~90x90; ico builds _square(base, max(sizes))
crop_small = crop3  # ~90x90 square
print("small crop size:", crop_small.size)
ico_sizes = [s for s in ICO_SIZES if s <= 256]
sq_for_ico = io_utils._square(crop_small, max(ico_sizes))
print("io_utils._square upscales small crop to:", sq_for_ico.size, "(max ICO size", max(ico_sizes), ")")
# Now the 16px frame inside ICO is downscaled FROM this upscaled 256. Compare to
# direct downscale from the 90px original.
direct16 = io_utils._square(crop_small, 16)
via256 = io_utils._square(sq_for_ico, 16)
print("HF direct 90->16:", round(hf_energy(direct16),3),
      " via 90->256->16:", round(hf_energy(via256),3))


# =====================================================================
banner("TEST 7: contact-sheet correctness")
sheet_art = [a for a in res.artifacts if a.kind == "sheet"]
if sheet_art:
    sh = Image.open(io.BytesIO(sheet_art[0].data))
    print("contact-sheet size:", sh.size)
    # how many cells expected
    rendered = res.rendered
    print("rendered sizes:", [r.size for r in rendered])
    print("alpha flags:", [(r.size, r.has_alpha) for r in rendered])

print("\nDONE")
