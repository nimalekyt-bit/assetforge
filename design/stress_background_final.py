"""Final confirmation: exact failure boundaries + despill destruction."""
from __future__ import annotations
import numpy as np
from PIL import Image, ImageDraw
from assetforge.core.background import remove_background
from assetforge.core.config import BackgroundConfig

W = H = 256

def quick(img):
    res = remove_background(img, BackgroundConfig(mode="auto"))
    a = np.asarray(res.image.convert("RGBA"))[:, :, 3]
    cy, cx = H // 2, W // 2
    cm = float(a[cy-12:cy+12, cx-12:cx+12].mean())
    rgb = np.asarray(res.image.convert("RGBA"))[cy, cx, :3]
    return res.detected_mode, cm, tuple(int(v) for v in rgb)

print("=== Green-screen: ANY object with g>r,b gets desaturated to grey by despill ===")
for obj in [(40,160,60),(120,200,80),(255,255,0),(0,200,0),(80,180,40)]:
    img = Image.new("RGBA",(W,H),(20,200,30,255))
    d=ImageDraw.Draw(img); d.ellipse([W//4,H//4,3*W//4,3*H//4],fill=(*obj,255))
    m,cm,rgb=quick(img)
    eaten = "EATEN(alpha=0)" if cm<8 else f"alpha={cm:.0f}"
    print(f"  obj {obj} -> {eaten}  centerRGB {rgb} (G {obj[1]}->{rgb[1]})")

print("\n=== Yellow object (255,255,0) on green: green channel legit, despill kills it ===")
img = Image.new("RGBA",(W,H),(20,200,30,255))
d=ImageDraw.Draw(img); d.ellipse([W//4,H//4,3*W//4,3*H//4],fill=(255,255,0,255))
m,cm,rgb=quick(img)
print(f"  yellow obj -> mode={m} alpha={cm:.0f} centerRGB={rgb} (expected ~255,255,0)")

print("\n=== 'none' lockout: object present but too close to white -> NO removal at all ===")
for v in (255,252,250,248,246,244,242,240):
    img=Image.new("RGBA",(W,H),(255,255,255,255))
    d=ImageDraw.Draw(img); d.ellipse([W//4,H//4,3*W//4,3*H//4],fill=(v,v,v,255))
    m,cm,rgb=quick(img)
    print(f"  obj grey={v} on white -> mode={m} center_alpha={cm:.0f}")

print("\n=== checker false-positive on gradients eats grey objects ===")
def grad(ct,cb,obj):
    arr=np.zeros((H,W,4),np.uint8)
    for y in range(H):
        t=y/(H-1)
        for c in range(3): arr[y,:,c]=int(ct[c]*(1-t)+cb[c]*t)
        arr[y,:,3]=255
    im=Image.fromarray(arr,"RGBA"); d=ImageDraw.Draw(im)
    d.ellipse([W//4,H//4,3*W//4,3*H//4],fill=(*obj,255)); return im
for obj in [(200,200,200),(190,190,190),(180,180,180),(210,210,210)]:
    m,cm,rgb=grad((230,230,230),(170,170,170),obj) and quick(grad((230,230,230),(170,170,170),obj))
    print(f"  grad grey obj={obj} -> mode={m} center_alpha={cm:.0f}")
