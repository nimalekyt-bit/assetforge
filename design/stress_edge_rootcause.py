"""Root-cause: color-distance ramp vs spatial coverage; tuning sensitivity;
dark fringe on chroma white-edge; thin-line antialias collapse."""
from __future__ import annotations
import sys
import numpy as np
from PIL import Image
sys.path.insert(0, r"E:\photovirez")
from assetforge.core.background import remove_background
from assetforge.core.config import BackgroundConfig


def sec(s): print("\n" + "=" * 72 + "\n" + s + "\n" + "=" * 72)


def make_disk_on_white(size=200, radius=70, fill=(40, 90, 200), ss=4):
    big = np.full((size*ss, size*ss, 3), 255, np.float32)
    yy, xx = np.mgrid[0:size*ss, 0:size*ss]
    d = np.sqrt((xx-size*ss/2)**2 + (yy-size*ss/2)**2)
    big[d <= radius*ss] = fill
    img = Image.fromarray(big.astype(np.uint8)).resize((size, size), Image.LANCZOS)
    cov = (d <= radius*ss).astype(np.float32)
    gtc = np.asarray(Image.fromarray((cov*255).astype(np.uint8)).resize((size, size), Image.LANCZOS)).astype(np.float32)/255.0
    return img, gtc


# ---- E) Sweep softness/tolerance: does any setting recover the AA edge?
sec("E) Sweep softness to recover AA coverage (disk on white)")
img, gtc = make_disk_on_white()
edge = (gtc > 0.05) & (gtc < 0.95)
print(f"true AA edge px = {int(edge.sum())}")
print(f"{'tol':>4} {'soft':>5} {'alpha_err':>9} {'halo_black':>10} {'edge_px':>8}")
for tol, soft in [(32, 24), (16, 24), (8, 40), (0, 60), (0, 120), (4, 200), (0, 255)]:
    res = remove_background(img, BackgroundConfig(mode="white", tolerance=tol, softness=soft))
    out = np.asarray(res.image).astype(np.float32)
    oa = out[:, :, 3]/255.0
    aerr = np.abs(oa[edge]-gtc[edge]).mean()
    on_black = (out[:, :, :3]*oa[:, :, None])[edge]
    ideal = np.array([40, 90, 200], np.float32)[None, :]*oa[edge][:, None]
    halo = on_black.mean()-ideal.mean()
    eb = ((oa > 0.03) & (oa < 0.97))
    print(f"{tol:>4} {soft:>5} {aerr:>9.3f} {halo:>+10.1f} {int(eb.sum()):>8}")
print("(alpha_err: |engine_alpha - true_coverage| on the AA band; lower=better)")
print("(halo_black: edge brightness excess over ideal premultiplied; >0 = light halo)")


# ---- F) Chroma white-on-green: dark fringe on black composite
sec("F) White object on green: dark fringe (edge too dark on black)")
ss = 4
arr = np.zeros((200*ss, 200*ss, 3), np.float32)
arr[:, :] = [20, 200, 30]
yy, xx = np.mgrid[0:200*ss, 0:200*ss]
d = np.sqrt((xx-100*ss)**2 + (yy-100*ss)**2)
arr[d <= 60*ss] = [240, 240, 240]
img = Image.fromarray(arr.astype(np.uint8)).resize((200, 200), Image.LANCZOS)
res = remove_background(img, BackgroundConfig(mode="chroma"))
out = np.asarray(res.image).astype(np.float32)
oa = out[:, :, 3]/255.0
edge = (oa > 0.05) & (oa < 0.95)
em = out[:, :, :3][edge]
print(f"edge stored RGB mean: {em.mean(axis=0).round(1).tolist()} (object is white 240)")
print(f"  -> if << 240 and tinted, dark/colored fringe on the edge")
# composite on black & white
ob = (out[:, :, :3]*oa[:, :, None])[edge]
print(f"edge on BLACK brightness: {ob.mean():.1f}")
green_excess = em[:, 1] - (em[:, 0]+em[:, 2])/2
print(f"residual green excess on edge: mean={green_excess.mean():.1f} max={green_excess.max():.1f}")
neg = em[:, 1] - (em[:, 0]+em[:, 2])/2
print(f"magenta tint (negative green excess) min={neg.min():.1f} "
      f"(<0 => over-despilled to magenta)")


# ---- G) Thin lines: detect=none means lines pass through untouched on a uniform
#         white field that *should* have been removed
sec("G) Thin lines on white: bg removal gives up (mode=none)")
size = 200; ss = 4
big = np.full((size*ss, size*ss, 3), 255, np.float32)
for i in range(1, 8):
    x = int(i*size*ss/8); w = max(ss, i*ss//2)
    big[:, x:x+w] = [20, 20, 20]
img = Image.fromarray(big.astype(np.uint8)).resize((size, size), Image.LANCZOS)
res = remove_background(img, BackgroundConfig(mode="auto"))
print("auto mode ->", res.detected_mode, res.notes[-1] if res.notes else "")
print("transparent_frac:", round(float((np.asarray(res.image)[:,:,3] < 16).mean()), 3),
      "(0 => white NOT removed, whole frame opaque)")
# force white
res2 = remove_background(img, BackgroundConfig(mode="white"))
ta = float((np.asarray(res2.image)[:,:,3] < 16).mean())
print("forced white mode -> transparent_frac:", round(ta, 3))

print("\nDONE")
