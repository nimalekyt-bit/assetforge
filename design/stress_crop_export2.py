# -*- coding: utf-8 -*-
"""Deeper measurements: double-padding, ico/icns silent drop & size capping,
sharpness vs naive, square mismatch when crop.square but called with square=False."""
from __future__ import annotations
import io, sys, math
import numpy as np
from PIL import Image

sys.path.insert(0, r"E:\photovirez")
from assetforge.core.config import (CropConfig, ResizeConfig, ExportConfig,
                                     ICO_SIZES, ICNS_SIZES, ICON_SIZES)
from assetforge.core import crop as crop_mod, resize as resize_mod, export as export_mod
from assetforge.core import io_utils, detect, pipeline
from assetforge.core.config import PipelineConfig


def banner(s): print("\n" + "="*70 + "\n" + s + "\n" + "="*70)
def fill_ratio(im):
    """Fraction of canvas covered by content (alpha>16)."""
    a = np.asarray(im.convert("RGBA"))[:,:,3]
    return float((a > 16).sum()) / (a.shape[0]*a.shape[1])
def content_side_frac(im):
    bb = im.getbbox()
    if not bb: return None
    w,h = im.size
    return (bb[2]-bb[0])/w, (bb[3]-bb[1])/h


# =====================================================================
banner("A: DOUBLE-PADDING — does padding effectively apply twice?")
# A square object 200x200 with padding 6% in apply_crop. Then resize square=True.
# crop_to_bbox pads 6% (-> ~224x224 content+pad already letterboxed by paste? no).
# But content_side_frac after apply_crop vs after resize_to should be SAME.
im = Image.new("RGBA",(400,400),(0,0,0,0))
px=im.load()
for y in range(100,300):
    for x in range(100,300):
        px[x,y]=(200,50,50,255)
bb = detect.content_bbox(im,16)
print("bbox:",bb)
for pad in (0.0, 6.0, 20.0):
    cfg=CropConfig(fit="contain",square=True,padding_pct=pad)
    c=crop_mod.apply_crop(im,bb,cfg)
    r=resize_mod.resize_to(c,256,ResizeConfig(),square=True)
    print(f"  pad={pad:5}% -> apply_crop {c.size} fill={fill_ratio(c):.3f} side={content_side_frac(c)}"
          f"  | resized fill={fill_ratio(r):.3f} side={content_side_frac(r)}")


# =====================================================================
banner("B: NON-SQUARE crop into ICO when square=True (mismatch source)")
# Pipeline default: crop.square True, fit contain. apply_crop already makes square.
# But build_export's ico path calls _square(base,...) AGAIN. base is square crop.
# What if crop.fit=width but export still gets ico? stage_export sets square=False
# so ico skipped. But what if someone calls build_export(square=True) on a NON-square
# base (e.g. fit='none' but square=False in crop -> apply_crop returns NON-square)?
cfg=CropConfig(fit="none",square=False,padding_pct=0.0)
wide=Image.new("RGBA",(500,100),(0,0,0,0))
px=wide.load()
for y in range(5,95):
    for x in range(5,495):
        px[x,y]=(60,120,200,255)
# red marker left
for y in range(10,40):
    for x in range(10,40):
        px[x,y]=(255,0,0,255)
bbw=detect.content_bbox(wide,16)
cropw=crop_mod.apply_crop(wide,bbw,cfg)  # NON-square because square=False
print("apply_crop fit=none square=False ->", cropw.size, "(non-square)")
# Now if build_export is called with square=True on this non-square base:
res=export_mod.build_export(cropw, ExportConfig(sizes=[64,256],formats=["png","ico"]), ResizeConfig(), square=True)
png=[a for a in res.by_kind("png") if a.name.endswith("_256.png")][0]
pim=Image.open(io.BytesIO(png.data)).convert("RGBA")
ico=res.by_kind("ico")[0]
iim=Image.open(io.BytesIO(ico.data));
print("PNG256 side frac:",content_side_frac(pim))
# load ico 256 frame
fr=Image.open(io.BytesIO(ico.data)); fr.size=(256,256); fr.load(); fr=fr.convert("RGBA")
print("ICO256 side frac:",content_side_frac(fr))
# measure marker aspect (stretch check) in both
def marker_aspect(p):
    arr=np.asarray(p); red=(arr[:,:,0]>180)&(arr[:,:,1]<80)&(arr[:,:,2]<80)&(arr[:,:,3]>128)
    ys,xs=np.where(red)
    if not len(xs): return None
    return (xs.max()-xs.min()+1)/(ys.max()-ys.min()+1)
print("PNG marker aspect:",marker_aspect(pim)," ICO marker aspect:",marker_aspect(fr),"(orig square=1.0)")


# =====================================================================
banner("C: ICO/ICNS silently DROPPED for wordmark, no warning in meta")
cfgp=PipelineConfig()
cfgp.crop=CropConfig(fit="width",square=False)
cfgp.export=ExportConfig(sizes=[256,512],formats=["png","ico","icns"])
# emulate stage_export
cropped=crop_mod.apply_crop(wide,bbw,cfgp.crop)
square = cfgp.crop.square and cfgp.crop.fit!="width"
res=export_mod.build_export(cropped,cfgp.export,cfgp.resize,square=square,meta={})
kinds=sorted(set(a.kind for a in res.artifacts))
print("requested formats:",cfgp.export.formats," -> produced kinds:",kinds)
print("meta warnings:",res.meta.get("warnings","<none>"))
print("=> ICO/ICNS requested but absent and NO warning told to user")


# =====================================================================
banner("D: ICO/ICNS size capping when user picks SMALL max size")
# favicon-ish: user sizes [16,32,48] only. ICO should still hold those, fine.
# But launcher with sizes only up to 256? Windows wants up to 256 (ok). macOS .icns
# wants up to 1024. If max=256, icns capped to 256 -> Retina launcher blurry.
for sizes in ([16,32,48],[256],[16,32,64,128]):
    max_size=max(sizes)
    ico_sizes=[s for s in ICO_SIZES if s<=max_size]
    icns_sizes=[s for s in ICNS_SIZES if s<=max_size]
    print(f"  user sizes {sizes} (max {max_size}): ICO holds {ico_sizes}  ICNS holds {icns_sizes}")
print("ICNS_SIZES full:",ICNS_SIZES,"  ICO_SIZES full:",ICO_SIZES)


# =====================================================================
banner("E: SHARPNESS — engine vs naive single-step lanczos at 16/24/32")
def hf(im):
    arr=np.asarray(im.convert("RGBA")).astype(np.float64)
    lum=(0.299*arr[:,:,0]+0.587*arr[:,:,1]+0.114*arr[:,:,2])*(arr[:,:,3]/255.0)
    lap=(lum[:-2,1:-1]+lum[2:,1:-1]+lum[1:-1,:-2]+lum[1:-1,2:]-4*lum[1:-1,1:-1])
    return float(lap.var())
# fine-detail square 512
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
for size in (16,24,32):
    eng=resize_mod.resize_to(cropf,size,ResizeConfig(unsharp=True),square=True)
    # naive: pad-to-square then single lanczos, no unsharp
    naive=io_utils._square(cropf,size)
    print(f"  size {size}: engine HF={hf(eng):.1f}  naive HF={hf(naive):.1f}")


# =====================================================================
banner("F: clipping/overshoot from UnsharpMask (halos at edges)")
# Overshoot can push alpha or color beyond, producing ringing on the disk edge.
size=32
eng=resize_mod.resize_to(cropf,size,ResizeConfig(unsharp=True),square=True)
off=resize_mod.resize_to(cropf,size,ResizeConfig(unsharp=False),square=True)
ea=np.asarray(eng).astype(int); oa=np.asarray(off).astype(int)
# count pixels that became fully saturated (255) or fully dark (0) due to overshoot
sat_e=int(((ea[:,:,:3]==255).any(axis=2)&(ea[:,:,3]>0)).sum())
sat_o=int(((oa[:,:,:3]==255).any(axis=2)&(oa[:,:,3]>0)).sum())
print(f"  size 32 saturated(255) px: unsharp_on={sat_e} off={sat_o} (extra halos={sat_e-sat_o})")
# alpha overshoot
print("  alpha range on:",np.asarray(eng)[:,:,3].min(),np.asarray(eng)[:,:,3].max(),
      " off:",np.asarray(off)[:,:,3].min(),np.asarray(off)[:,:,3].max())


# =====================================================================
banner("G: HALO on dark/colored composite (premultiply check)")
# Resize on straight (non-premultiplied) alpha can create fringe on AA edge.
# Composite the 64px icon onto black and onto red, measure fringe energy.
icon=resize_mod.resize_to(cropf,64,ResizeConfig(),square=True)
def composite_fringe(icon,bg):
    base=Image.new("RGBA",icon.size,bg)
    base.alpha_composite(icon)
    arr=np.asarray(base).astype(np.float64)
    # look at semi-transparent ring: where original alpha in (10..245)
    al=np.asarray(icon)[:,:,3]
    ring=(al>10)&(al<245)
    if ring.sum()==0: return 0.0
    lum=0.299*arr[:,:,0]+0.587*arr[:,:,1]+0.114*arr[:,:,2]
    return float(lum[ring].mean())
print("  mean lum in AA ring on BLACK bg:",round(composite_fringe(icon,(0,0,0,255)),2))
print("  mean lum in AA ring on RED bg:  ",round(composite_fringe(icon,(255,0,0,255)),2))
print("  (dark halo if black-bg ring is much brighter than bg=0 from leaked color)")

print("\nDONE2")
