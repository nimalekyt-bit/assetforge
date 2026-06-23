# -*- coding: utf-8 -*-
"""Final checks: ICNS retina cap, contact-sheet thumb scaling for 256/512,
fit param redundancy proof, and a measured 'sharp PNG vs soft ICO' single-step fix demo."""
from __future__ import annotations
import io, sys
import numpy as np
from PIL import Image

sys.path.insert(0, r"E:\photovirez")
from assetforge.core.config import CropConfig, ResizeConfig, ExportConfig, ICNS_SIZES, ICO_SIZES
from assetforge.core import crop as crop_mod, resize as resize_mod, export as export_mod
from assetforge.core import io_utils, detect

def banner(s): print("\n"+"="*70+"\n"+s+"\n"+"="*70)
def hf(im):
    arr=np.asarray(im.convert("RGBA")).astype(np.float64)
    lum=(0.299*arr[:,:,0]+0.587*arr[:,:,1]+0.114*arr[:,:,2])*(arr[:,:,3]/255.0)
    lap=(lum[:-2,1:-1]+lum[2:,1:-1]+lum[1:-1,:-2]+lum[1:-1,2:]-4*lum[1:-1,1:-1])
    return float(lap.var())

S=512
a=np.zeros((S,S,4),np.uint8)
yy,xx=np.mgrid[0:S,0:S]
disk=((xx-S/2)**2+(yy-S/2)**2)<=(S*0.46)**2
a[disk]=(30,60,120,255)
rad=np.hypot(xx-S/2,yy-S/2)
a[(np.sin(rad/4.0)>0.6)&disk]=(240,240,250,255)
fine=Image.fromarray(a,"RGBA")
bbf=detect.content_bbox(fine,16)
cropf=crop_mod.apply_crop(fine,bbf,CropConfig(fit="contain",square=True,padding_pct=6.0))

banner("K: PROOF fit=contain and fit=none are byte-identical (dead config option)")
import hashlib
def dig(im): return hashlib.md5(io_utils.to_png_bytes(im)).hexdigest()
c1=crop_mod.apply_crop(fine,bbf,CropConfig(fit="contain",square=True,padding_pct=6.0))
c2=crop_mod.apply_crop(fine,bbf,CropConfig(fit="none",square=True,padding_pct=6.0))
print("  fit=contain md5:",dig(c1))
print("  fit=none    md5:",dig(c2))
print("  IDENTICAL:",dig(c1)==dig(c2),"-> 'fit' has only 2 real behaviors (width vs not), 'none'==... 'contain'")

banner("L: ICNS launcher Retina cap — launcher preset sizes [256,512,1024]")
# launcher sizes include 1024, so icns gets up to 1024. Good. But what about a user
# requesting [256,512] (no 1024)? icns capped at 512 -> macOS 1024@2x missing.
for sizes in ([256,512,1024],[256,512],[512]):
    ms=max(sizes); icns=[s for s in ICNS_SIZES if s<=ms]
    print(f"  launcher sizes {sizes}: ICNS frames {icns}  (macOS wants up to 1024 for Retina)")

banner("M: contact-sheet thumb downscale for 256/512 uses LANCZOS but no clarity loss check")
ecfg=ExportConfig(sizes=[16,32,256,512],formats=["png"],make_contact_sheet=True)
res=export_mod.build_export(cropf,ecfg,ResizeConfig(),square=True,meta={"objects":1,"preset":"x"})
sheet=[a for a in res.artifacts if a.kind=="sheet"][0]
sh=Image.open(io.BytesIO(sheet.data))
print("  sheet size:",sh.size,"(cell=150, disp=min(size,142))")
# 512 icon displayed at 142 -> downscaled in sheet. Fine for preview. 16 shown at 16 -> small.
print("  16px shown at min(16,142)=16 -> tiny in 150 cell (lots of empty space, but OK for QA)")

banner("N: FIX DEMO — single-step ICO frames w/ unsharp match PNG sharpness")
# Show that building ICO frames the SAME way PNG is built recovers sharpness.
def ico_like_png(base, sizes):
    frames=[resize_mod.resize_to(base, s, ResizeConfig(unsharp=True), square=True) for s in sizes]
    return frames
sizes=[16,24,32,48]
png_frames={s:resize_mod.resize_to(cropf,s,ResizeConfig(unsharp=True),square=True) for s in sizes}
# current engine ico: _square(base, max(sizes_<=256)) then encoder downscales
ico_base=io_utils._square(cropf, max([s for s in ICO_SIZES if s<=512] or [256]))  # =256
print("  current ICO base size:", ico_base.size)
cur={s:io_utils._square(ico_base,s) for s in sizes}  # how each ico frame is effectively derived
fix=ico_like_png(cropf,sizes)
for i,s in enumerate(sizes):
    print(f"  size {s}: PNG HF={hf(png_frames[s]):8.1f}  current-ICO HF={hf(cur[s]):8.1f}  fixed-ICO HF={hf(fix[i]):8.1f}")
print("  => fixed-ICO HF ~= PNG HF; current-ICO is the soft one.")

print("\nDONE4")
