"""Confirm root causes: solid k-broadcast memory, analyze-no-downscale impact,
and the dirty-alpha halo as composited artifact on real backgrounds."""
from __future__ import annotations
import gc, time, tracemalloc
import numpy as np
from PIL import Image
from assetforge.core.background import remove_background
from assetforge.core.config import BackgroundConfig, PipelineConfig
from assetforge.core import detect, pipeline
from assetforge.core import io_utils

def arr(im): return np.asarray(im.convert("RGBA"))
def transp(im): return float((arr(im)[:,:,3]<16).mean())

print("="*70); print("MEMORY breakdown: solid path (H,W,k,3) array size")
print("="*70)
H=W=4000
# solid path: d = ((rgb[:,:,None,:]-K[None,None,:,:])**2).sum(3) ; rgb float32 (H,W,3)
# intermediate (H,W,1,3) float32 = 4000*4000*3*4 = 192MB then **2 another 192MB, sum->(H,W,1)
print(f"  rgb float32 (H,W,3)        = {H*W*3*4/1e6:.0f} MB")
print(f"  (rgb[:,:,None,:]-K) f32     = {H*W*1*3*4/1e6:.0f} MB  (k=1)")
print(f"  ...**2 temp                 = {H*W*1*3*4/1e6:.0f} MB")
print(f"  d distances (H,W,k)         = {H*W*1*4/1e6:.0f} MB")
print("  Plus arr float32 (256MB) + out copy (256MB) + decontaminate copy (256MB)")

# What about a checker bg -> 2 keys: k=2 doubles the (H,W,k,3) temporaries
a = np.zeros((H,W,4), np.uint8); a[:,:,3]=255
# checkerboard light/gray bg
tile=64
yy,xx=np.mgrid[0:H,0:W]
chk=((xx//tile + yy//tile)%2).astype(bool)
a[chk,:3]=230; a[~chk,:3]=200
a[1500:2500,1500:2500,:3]=[200,40,40]  # object
im=Image.fromarray(a,"RGBA")
gc.collect(); tracemalloc.start(); t0=time.perf_counter()
r=remove_background(im, BackgroundConfig(mode="auto"))
dt=(time.perf_counter()-t0)*1000; _,pk=tracemalloc.get_traced_memory(); tracemalloc.stop()
print(f"  CHECKER 4000x4000 auto: {dt:.0f}ms peak +{pk/1e6:.0f}MB detected={r.detected_mode}")

print("\n"+"="*70); print("IMPACT: analyze never downscales — compare to downscaled path")
print("="*70)
im2=Image.new("RGBA",(4000,4000),(250,250,250,255))
b=arr(im2).copy(); b[1000:3000,1000:3000,:3]=[200,50,50]; im2=Image.fromarray(b,"RGBA")
gc.collect(); tracemalloc.start(); t0=time.perf_counter()
an=pipeline.analyze(im2)
dt=(time.perf_counter()-t0)*1000; _,pk=tracemalloc.get_traced_memory(); tracemalloc.stop()
print(f"  analyze full 4000x4000: {dt:.0f}ms peak +{pk/1e6:.0f}MB")
small=io_utils.downscale_for_analysis(im2)
gc.collect(); tracemalloc.start(); t0=time.perf_counter()
an2=pipeline.analyze(small)
dt=(time.perf_counter()-t0)*1000; _,pk=tracemalloc.get_traced_memory(); tracemalloc.stop()
print(f"  analyze on 1600 downscaled: {dt:.0f}ms peak +{pk/1e6:.0f}MB (helper exists but unused)")

print("\n"+"="*70); print("HALO: realistic dark-fringe object photographed on white")
print("="*70)
# product shot: gray object with dark anti-alias outline on near-white bg
H=W=400
a=np.full((H,W,4),248,np.uint8)         # near-white studio bg
a[120:280,120:280,:3]=[180,180,185]     # light gray product
# soft dark contamination ring (JPEG/edge halo), 3px, value ~60
for d in range(3):
    for r0,c0,r1,c1 in [(117+d,117,121+d,283),(279-d,117,283-d,283),
                        (117,117+d,283,121+d),(117,279-d,283,283-d)]:
        a[r0:r1,c0:c1,:3]=60
im=Image.fromarray(a,"RGBA")
res=remove_background(im, BackgroundConfig(mode="auto"))
o=arr(res.image)
print(f"  detected={res.detected_mode} transp={transp(res.image):.1%}")
# composite over typical web backgrounds and measure dark-halo contrast
for bg,name in [((255,255,255),"white page"),((20,22,28),"dark UI"),((0,120,255),"blue")]:
    al=o[:,:,3:4]/255.0; comp=(o[:,:,:3]*al+np.array(bg)*(1-al)).astype(np.uint8)
    ring=comp[118,120:280].mean(axis=0)   # the dark ring row
    inside=comp[200,200]
    print(f"  on {name:9s}: dark-ring RGB={ring.round(0)} vs product RGB={inside}")
dark_opaque=int(((o[:,:,:3].max(2)<90)&(o[:,:,3]>128)).sum())
print(f"  surviving dark halo pixels (rgb<90,alpha>128): {dark_opaque}")

print("\n"+"="*70); print("GRID 64x64 floods many micro-boxes (export cost)")
print("="*70)
a=np.zeros((512,512,4),np.uint8); a[:,:,3]=255
im=Image.fromarray(a,"RGBA")
boxes=detect.split_objects(im,mode="grid",grid_rows=64,grid_cols=64)
tiny=[b for b in boxes if (b[2]-b[0])<=8]
print(f"  grid64x64 on full-512: {len(boxes)} boxes, {len(tiny)} are <=8px wide")
# pipeline.run would export EACH -> count
cfg=PipelineConfig(); cfg.crop.split="grid"; cfg.crop.grid_rows=16; cfg.crop.grid_cols=16
an=pipeline.analyze(im,cfg)
print(f"  analyze grid16x16 on solid 512: objects={an.meta['objects']} (run() exports all)")

print("\nDONE")
