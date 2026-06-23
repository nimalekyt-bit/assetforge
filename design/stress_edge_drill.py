"""Deeper drill-down on the strongest findings."""
from __future__ import annotations
import sys
import numpy as np
from PIL import Image
sys.path.insert(0, r"E:\photovirez")
from assetforge.core.background import remove_background, detect_background, _color_key, _decontaminate_edge
from assetforge.core.config import BackgroundConfig


def sec(s): print("\n" + "=" * 72 + "\n" + s + "\n" + "=" * 72)


# ---- A) translucent glow: quantify how much real translucency gets flattened
sec("A) Translucent soft glow on white: alpha fidelity profile")
size = 200
yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
cx = cy = size / 2
d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
r = size * 0.42
gt = np.clip(1.0 - d / r, 0.0, 1.0) ** 1.5 * (140 / 255.0)
fill = np.array([220, 60, 60], np.float32)
white = np.array([255, 255, 255], np.float32)
a3 = gt[:, :, None]
rgb = fill * a3 + white * (1 - a3)
img = Image.fromarray(rgb.astype(np.uint8), "RGB")
res = remove_background(img, BackgroundConfig(mode="white"))
out_a = np.asarray(res.image)[:, :, 3].astype(np.float32) / 255.0
# sample radial profile
for rad in [0, 10, 20, 30, 40, 50, 60, 70, 80]:
    m = (np.abs(d - rad) < 1.5)
    if m.any():
        print(f"r={rad:3d}  GT_alpha={gt[m].mean():.3f}  OUT_alpha={out_a[m].mean():.3f}  "
              f"err={out_a[m].mean()-gt[m].mean():+.3f}")
# overall
print(f"\nGT total alpha mass: {gt.sum():.0f}   OUT total alpha mass: {out_a.sum():.0f}  "
      f"ratio={out_a.sum()/gt.sum():.3f}")
print(f"px where GT in (0.05,0.5) [genuine translucency]: {int(((gt>0.05)&(gt<0.5)).sum())}")
m_trans = (gt > 0.05) & (gt < 0.5)
print(f"  of those, OUT alpha forced to >0.95 (over-opaqued): "
      f"{int((out_a[m_trans]>0.95).sum())}")
print(f"  of those, OUT alpha killed to <0.05 (eaten): "
      f"{int((out_a[m_trans]<0.05).sum())}")


# ---- B) low-alpha decontam overshoot: direct unit test of _decontaminate_edge
sec("B) _decontaminate_edge low-alpha amplification (synthetic)")
# A true edge pixel: object=(30,60,220), bg/key=(200,40,40), alpha=0.04
# observed = obj*a + key*(1-a)
key = np.array([200, 40, 40], np.float32)
obj_true = np.array([30, 60, 220], np.float32)
for a in [0.5, 0.2, 0.1, 0.05, 0.02, 0.01]:
    observed = obj_true * a + key * (1 - a)
    arr = np.zeros((1, 1, 4), np.float32)
    arr[0, 0, :3] = observed
    arr[0, 0, 3] = a * 255
    ramp = np.array([[a]], np.float32)
    out = _decontaminate_edge(arr, ramp, key)
    recovered = out[0, 0, :3]
    err = np.abs(recovered - obj_true).max()
    clipped = ((recovered <= 0.5) | (recovered >= 254.5)).any()
    print(f"a={a:.2f}  recovered={recovered.round(1).tolist()}  "
          f"true={obj_true.tolist()}  maxerr={err:.1f}  clipped={clipped}")
print("note: with quantized uint8 input, even tiny noise in 'observed' divides by a")
# now with quantized observed (uint8 round) — realistic
print("\n-- with uint8 quantization of observed (realistic) --")
for a in [0.2, 0.1, 0.05, 0.02]:
    observed = np.round(obj_true * a + key * (1 - a))  # uint8 rounding
    arr = np.zeros((1, 1, 4), np.float32)
    arr[0, 0, :3] = observed
    arr[0, 0, 3] = a * 255
    ramp = np.array([[a]], np.float32)
    out = _decontaminate_edge(arr, ramp, key)
    recovered = out[0, 0, :3]
    err = np.abs(recovered - obj_true).max()
    print(f"a={a:.2f}  observed(uint8)={observed.tolist()}  recovered={recovered.round(1).tolist()}  maxerr={err:.1f}")


# ---- C) white-circle light-halo on black: is the edge brighter than a clean edge?
sec("C) Solid AA disk on white: edge halo vs ideal premultiplied edge")
SS = 4
big = np.full((size*SS, size*SS, 3), 255, np.float32)
yyb, xxb = np.mgrid[0:size*SS, 0:size*SS]
db = np.sqrt((xxb-size*SS/2)**2 + (yyb-size*SS/2)**2)
big[db <= 70*SS] = [40, 90, 200]
img = Image.fromarray(big.astype(np.uint8)).resize((size, size), Image.LANCZOS)
# Ground truth alpha = coverage of the disk = downscaled binary mask
covmask = (db <= 70*SS).astype(np.float32)
gt_cov = np.asarray(Image.fromarray((covmask*255).astype(np.uint8)).resize((size, size), Image.LANCZOS)).astype(np.float32)/255.0
res = remove_background(img, BackgroundConfig(mode="white"))
out = np.asarray(res.image).astype(np.float32)
oa = out[:, :, 3]/255.0
edge = (oa > 0.03) & (oa < 0.97)
# ideal: object blue (40,90,200) premultiplied; on black comp = obj*alpha
ideal_black = np.array([40, 90, 200], np.float32)[None, :] * oa[edge][:, None]
on_black = out[edge][:, :3] * oa[edge][:, None]
diff = on_black - ideal_black
print(f"edge px: {int(edge.sum())}")
print(f"mean stored edge RGB: {out[edge][:,:3].mean(axis=0).round(1).tolist()} "
      f"(object is [40,90,200]; if pulled toward 255 => white-halo residue)")
print(f"on-black edge brightness mean: {on_black.mean():.1f}  ideal: {ideal_black.mean():.1f}  "
      f"excess(light halo): {on_black.mean()-ideal_black.mean():+.1f}")
# also compare alpha vs gt coverage
print(f"alpha vs gt coverage: mean|err| over edge = {np.abs(oa[edge]-gt_cov[edge]).mean():.3f}")
# Is the soft band wider/narrower than the true AA? count edge px
true_edge = (gt_cov > 0.03) & (gt_cov < 0.97)
print(f"true AA edge px: {int(true_edge.sum())}   engine edge px: {int(edge.sum())}  "
      f"(engine band {'WIDER' if edge.sum()>true_edge.sum() else 'narrower/equal'})")


# ---- D) Does softness/tolerance erode antialiased edges? (matte choke)
sec("D) Edge erosion: alpha undershoot at the true AA boundary")
# Using same disk; measure where GT coverage ~0.5 what engine alpha is
band = np.abs(gt_cov - 0.5) < 0.05
if band.any():
    print(f"at GT coverage~0.5: engine alpha mean={oa[band].mean():.3f} "
          f"(should be ~0.5; <0.5 => choke/erosion, >0.5 => dilation)")
band2 = np.abs(gt_cov - 0.25) < 0.05
if band2.any():
    print(f"at GT coverage~0.25: engine alpha mean={oa[band2].mean():.3f} (ideal 0.25)")
band3 = np.abs(gt_cov - 0.75) < 0.05
if band3.any():
    print(f"at GT coverage~0.75: engine alpha mean={oa[band3].mean():.3f} (ideal 0.75)")

print("\nDONE")
