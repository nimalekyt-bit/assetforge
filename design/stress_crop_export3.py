# -*- coding: utf-8 -*-
"""Sharpness discrepancy PNG vs ICO frames (two-step resize), and premultiply halo."""
from __future__ import annotations
import io, sys
import numpy as np
from PIL import Image

sys.path.insert(0, r"E:\photovirez")
from assetforge.core.config import CropConfig, ResizeConfig, ExportConfig
from assetforge.core import crop as crop_mod, resize as resize_mod, export as export_mod
from assetforge.core import io_utils, detect

def banner(s): print("\n"+"="*70+"\n"+s+"\n"+"="*70)
def hf(im):
    arr=np.asarray(im.convert("RGBA")).astype(np.float64)
    lum=(0.299*arr[:,:,0]+0.587*arr[:,:,1]+0.114*arr[:,:,2])*(arr[:,:,3]/255.0)
    lap=(lum[:-2,1:-1]+lum[2:,1:-1]+lum[1:-1,:-2]+lum[1:-1,2:]-4*lum[1:-1,1:-1])
    return float(lap.var())

# fine detail 512 disk
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
print("cropf:",cropf.size)

banner("H: PNG 16/24/32 vs ICO 16/24/32 frame sharpness (two-step in ICO)")
ecfg=ExportConfig(sizes=[16,24,32,48,64,128,256,512],formats=["png","ico"],make_contact_sheet=False)
res=export_mod.build_export(cropf,ecfg,ResizeConfig(),square=True)
pngs={}
for art in res.by_kind("png"):
    s=int(art.name.split("_")[-1].split(".")[0])
    pngs[s]=Image.open(io.BytesIO(art.data)).convert("RGBA")
ico=res.by_kind("ico")[0]
for s in (16,24,32,48):
    fr=Image.open(io.BytesIO(ico.data)); fr.size=(s,s); fr.load(); fr=fr.convert("RGBA")
    p=pngs[s]
    # SSIM-lite: mean abs diff of luminance, plus HF compare
    pa=np.asarray(p).astype(float); fa=np.asarray(fr).astype(float)
    diff=np.abs(pa[:,:,:3].mean(2)-fa[:,:,:3].mean(2)).mean()
    print(f"  size {s:3d}: PNG HF={hf(p):8.1f}  ICO HF={hf(fr):8.1f}  ratio(ico/png)={hf(fr)/max(1e-9,hf(p)):.3f}  meanLumDiff={diff:.2f}")

print("\n  => If ICO HF << PNG HF, ICO frames are softer (two-step 512->256->N, no unsharp)")
print("  PNG path applies UnsharpMask at small sizes; ICO encoder does NOT.")

banner("I: PREMULTIPLY halo — colored object on transparency, downscale, composite")
# Hard-edge bright green object surrounded by transparency. If resize uses straight
# alpha, the (R,G,B) of fully-transparent pixels (often 0,0,0) bleeds into AA edge.
big=Image.new("RGBA",(400,400),(0,0,0,0))  # transparent pixels are (0,0,0,0) -> black RGB
px=big.load()
for y in range(120,280):
    for x in range(120,280):
        px[x,y]=(0,255,0,255)   # pure green block
bb=detect.content_bbox(big,16)
cb=crop_mod.apply_crop(big,bb,CropConfig(fit="contain",square=True,padding_pct=10.0))
small=resize_mod.resize_to(cb,32,ResizeConfig(unsharp=False),square=True)
arr=np.asarray(small).astype(int)
al=arr[:,:,3]
ring=(al>20)&(al<235)
# In the AA ring, what is the GREEN value? If premultiplied/clean, green stays high
# where alpha is partial; if straight-alpha bleed of black, green is pulled down.
if ring.sum():
    g=arr[:,:,1][ring]; r=arr[:,:,0][ring]; b=arr[:,:,2][ring]
    print(f"  AA-ring px={int(ring.sum())} meanG={g.mean():.1f} meanR={r.mean():.1f} meanB={b.mean():.1f}")
    # composite on white -> dark fringe shows as gray ring
    onwhite=Image.new("RGBA",small.size,(255,255,255,255)); onwhite.alpha_composite(small)
    wa=np.asarray(onwhite).astype(int)
    # ring luminance on white: pure green over white at alpha a -> mix; dark fringe lowers it oddly
    print(f"  composite-on-white ring meanRGB=({wa[:,:,0][ring].mean():.0f},{wa[:,:,1][ring].mean():.0f},{wa[:,:,2][ring].mean():.0f})")
    print("  (if R,B are elevated equally it's clean alpha-blend; a dark dip in G = black bleed)")

banner("J: does transparent RGB (0,0,0) bleed? compare to white-RGB transparent source")
# Make identical green block but with transparent pixels set to (255,255,255,0)
big2=Image.new("RGBA",(400,400),(255,255,255,0))
px=big2.load()
for y in range(120,280):
    for x in range(120,280):
        px[x,y]=(0,255,0,255)
bb2=detect.content_bbox(big2,16)
cb2=crop_mod.apply_crop(big2,bb2,CropConfig(fit="contain",square=True,padding_pct=10.0))
small2=resize_mod.resize_to(cb2,32,ResizeConfig(unsharp=False),square=True)
a1=np.asarray(small).astype(int); a2=np.asarray(small2).astype(int)
al1=a1[:,:,3]; al2=a2[:,:,3]
ring1=(al1>20)&(al1<235); ring2=(al2>20)&(al2<235)
print("  transparent-RGB=BLACK  AA ring meanRGB:",
      (round(a1[:,:,0][ring1].mean(),1),round(a1[:,:,1][ring1].mean(),1),round(a1[:,:,2][ring1].mean(),1)))
print("  transparent-RGB=WHITE  AA ring meanRGB:",
      (round(a2[:,:,0][ring2].mean(),1),round(a2[:,:,1][ring2].mean(),1),round(a2[:,:,2][ring2].mean(),1)))
print("  If these differ a lot, resize bleeds the transparent RGB into edges (no premultiply).")

print("\nDONE3")
