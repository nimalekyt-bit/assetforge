"""Deep-dive on the most concerning edge cases: memory blowup, extreme aspect,
dirty-alpha decontamination correctness, solid-mode 2-key broadcast cost."""
from __future__ import annotations

import gc
import time
import tracemalloc

import numpy as np
from PIL import Image

from assetforge.core.background import remove_background, detect_background, _color_key
from assetforge.core.config import BackgroundConfig
from assetforge.core import detect


def arr(im):
    return np.asarray(im.convert("RGBA"))


def transp(im):
    return float((arr(im)[:, :, 3] < 16).mean())


print("=" * 70)
print("A. MEMORY: where does 1.3GB come from for 16MP (256MB raw RGBA)?")
print("=" * 70)
# raw RGBA float32 = 4000*4000*4*4 = 256MB. distance math in _color_key:
# solid path builds d = (rgb[:,:,None,:]-K[None,None,:,:])**2 -> shape (H,W,k,3) float
# white/solid is k=1 -> (4000,4000,1,3) float64? rgb is float32 from .astype(np.float32)
H = W = 4000
im = Image.new("RGBA", (W, H), (250, 250, 250, 255))
a = arr(im).copy()
a[1000:3000, 1000:3000, :3] = [200, 50, 50]
im = Image.fromarray(a, "RGBA")

print(f"raw RGBA uint8 = {W*H*4/1e6:.0f} MB ; as float32 = {W*H*4*4/1e6:.0f} MB")

# measure each forced mode peak
for mode in ("white", "solid", "auto", "alpha", "none"):
    gc.collect(); tracemalloc.start()
    t0 = time.perf_counter()
    r = remove_background(im, BackgroundConfig(mode=mode))
    dt = (time.perf_counter() - t0) * 1000
    _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    print(f"  mode={mode:6s}: {dt:7.0f} ms, peak +{peak/1e6:5.0f} MB, detected={r.detected_mode}")

print("\nIf this 4000x4000 came in via UI, note: pipeline.analyze does NOT downscale.")
print("io_utils.downscale_for_analysis exists (ANALYZE_MAX=1600) but pipeline.analyze")
print("calls load_rgba directly, never downscale_for_analysis. Confirm:")
import inspect
from assetforge.core import pipeline
src = inspect.getsource(pipeline.analyze)
print("  'downscale' in analyze():", "downscale" in src)


print("\n" + "=" * 70)
print("B. EXTREME ASPECT: why detect=none for 8000x4?")
print("=" * 70)
# border frac=0.06 -> bh = max(1,int(4*0.06))=max(1,0)=1 row top+bottom; bw=int(8000*0.06)=480 cols
# So border is dominated by left/right 480-col strips. A vertical dark mark at center
# is INSIDE those strips? center=4000, strip is [0:480] and [7520:8000]. Mark at 3999:4001 -> NOT in border.
for W, H, mark in [(8000, 4, "center"), (8000, 4, "none"), (200, 200, "center")]:
    a = np.full((H, W, 4), 255, np.uint8)
    if mark == "center":
        a[:, W // 2 - 1:W // 2 + 1, :3] = 0
    im = Image.fromarray(a, "RGBA")
    mode, info = detect_background(arr(im).astype(np.float32))
    print(f"  {W}x{H} mark={mark}: detect={mode!r} ({info})")

# A real wide banner: white bg, dark text spanning width -> should be white-bg removable
a = np.full((60, 4000, 4), 245, np.uint8)
a[20:40, 100:3900, :3] = 30  # dark "text" band
im = Image.fromarray(a, "RGBA")
mode, info = detect_background(arr(im).astype(np.float32))
r = remove_background(im, BackgroundConfig(mode="auto"))
print(f"  4000x60 banner w/ text: detect={mode!r} ({info}) removed-transp={transp(r.image):.1%}")


print("\n" + "=" * 70)
print("C. DIRTY ALPHA decontamination — does dark fringe survive into output?")
print("=" * 70)
# White bg, red object, dark 2px contamination ring between them.
# After white-removal, the dark ring pixels: are they kept opaque (becoming a halo)
# or made transparent? Sample the actual ring alpha+rgb.
H = W = 300
a = np.full((H, W, 4), 255, np.uint8)
a[100:200, 100:200, :3] = [220, 40, 40]
a[98:100, 98:202, :3] = [20, 20, 20]   # top dark ring
a[200:202, 98:202, :3] = [20, 20, 20]
a[98:202, 98:100, :3] = [20, 20, 20]
a[98:202, 200:202, :3] = [20, 20, 20]
im = Image.fromarray(a, "RGBA")
r = remove_background(im, BackgroundConfig(mode="auto"))
o = arr(r.image)
# ring is at rows 98-99 (dark), object at 100-199
print(f"  detected={r.detected_mode}")
print(f"  dark-ring px (row98,col150): rgb={tuple(o[98,150,:3])} alpha={o[98,150,3]}")
print(f"  object px   (row150,col150): rgb={tuple(o[150,150,:3])} alpha={o[150,150,3]}")
print(f"  bg px       (row10,col10):   rgb={tuple(o[10,10,:3])} alpha={o[10,10,3]}")
# count surviving dark-fringe opaque pixels that AREN'T the object
mask_dark = (o[:, :, :3].max(axis=2) < 60) & (o[:, :, 3] > 200)
print(f"  surviving opaque dark pixels (potential halo): {int(mask_dark.sum())}")


print("\n" + "=" * 70)
print("D. SEMI-TRANSPARENT noise (clean_existing_alpha) and threshold gaps")
print("=" * 70)
# Object with alpha gradient 0..255; does 'alpha' mode preserve antialiasing?
a = np.zeros((100, 256, 4), np.uint8)
a[:, :, :3] = [200, 100, 50]
a[:, :, 3] = np.tile(np.arange(256, dtype=np.uint8), (100, 1))
im = Image.fromarray(a, "RGBA")
mode, info = detect_background(arr(im).astype(np.float32))
r = remove_background(im, BackgroundConfig(mode="auto"))
o = arr(r.image)
print(f"  alpha-gradient: detect={mode!r}({info})")
print(f"  alpha col5={o[50,5,3]} col128={o[50,128,3]} col255={o[50,255,3]} (should keep gradient)")

# 'dirty' near-zero alpha noise: alpha 1-3 scattered -> _clean_existing_alpha zeros <4
a = np.zeros((100, 100, 4), np.uint8)
a[:, :, :3] = 128
a[40:60, 40:60, 3] = 255
a[::3, ::3, 3] = 3   # speckle noise alpha=3
im = Image.fromarray(a, "RGBA")
b_full = detect.content_bbox(im, threshold=16)
print(f"  speckle alpha=3 + 20x20 solid: content_bbox(thr16)={b_full}")
b_low = detect.content_bbox(im, threshold=2)
print(f"  content_bbox(thr2)={b_low} (low thr lets speckle inflate bbox)")


print("\n" + "=" * 70)
print("E. GRID mode with 0 rows/cols and degenerate inputs")
print("=" * 70)
a = np.zeros((100, 100, 4), np.uint8)
a[10:90, 10:90, 3] = 255
im = Image.fromarray(a, "RGBA")
for gr, gc_ in [(0, 0), (3, 3), (1000, 1000)]:
    try:
        boxes = detect.split_objects(im, mode="grid", grid_rows=gr, grid_cols=gc_)
        print(f"  grid {gr}x{gc_}: {len(boxes)} boxes (first={boxes[0] if boxes else None})")
    except Exception as e:
        print(f"  grid {gr}x{gc_} RAISED: {type(e).__name__}: {e}")
# huge grid timing
a = np.zeros((2000, 2000, 4), np.uint8); a[:, :, 3] = 255
im = Image.fromarray(a, "RGBA")
t0 = time.perf_counter()
boxes = detect.split_objects(im, mode="grid", grid_rows=64, grid_cols=64)
print(f"  grid 64x64 on 2000x2000: {len(boxes)} boxes, {(time.perf_counter()-t0)*1000:.0f}ms")

print("\nDONE")
