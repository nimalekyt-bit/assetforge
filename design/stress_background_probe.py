"""Deep-dive probes for the suspected failures."""
from __future__ import annotations
import numpy as np
from PIL import Image, ImageDraw

from assetforge.core.background import remove_background, detect_background
from assetforge.core.config import BackgroundConfig

W = H = 256


def analyze(name, img, expected_mode=None):
    res = remove_background(img, BackgroundConfig(mode="auto"))
    a = np.asarray(res.image.convert("RGBA"))[:, :, 3]
    h, w = a.shape
    transp = float((a < 16).mean())
    cy, cx = h // 2, w // 2
    cregion = a[cy - 12:cy + 12, cx - 12:cx + 12]
    corners = [int(a[2, 2]), int(a[2, w - 3]), int(a[h - 3, 2]), int(a[h - 3, w - 3])]
    print(f"--- {name}")
    print(f"    mode={res.detected_mode} (exp {expected_mode}) transp={transp:.3f} "
          f"center_mean={cregion.mean():.0f} corners={corners}")
    print(f"    notes={res.notes}")
    return res, cregion.mean(), transp


def make_checker(w, h, c1, c2, cell, obj_color):
    img = Image.new("RGBA", (w, h), (*c1, 255))
    d = ImageDraw.Draw(img)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            if ((x // cell) + (y // cell)) % 2 == 0:
                d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(*c2, 255))
    d.ellipse([w // 4, h // 4, 3 * w // 4, 3 * h // 4], fill=(*obj_color, 255))
    return img


print("=" * 60)
print("PROBE 1: COLORED checker - object that is close to ONE of the keys")
print("=" * 60)
# blue/lightblue checker, object is mid-blue (between the two tones) -> eaten?
analyze("blue checker, obj=mid-blue (100,140,230)",
        make_checker(W, H, (40, 80, 200), (120, 160, 240), 16, (100, 140, 230)), "should keep obj")
# blue checker, object is white
analyze("blue checker, obj=white",
        make_checker(W, H, (40, 80, 200), (120, 160, 240), 16, (255, 255, 255)), "should keep obj")
# blue checker, object is a DIFFERENT blue (sky blue logo)
analyze("blue checker, obj=cyan (60,180,220)",
        make_checker(W, H, (40, 80, 200), (120, 160, 240), 16, (60, 180, 220)), "should keep cyan obj")

print("=" * 60)
print("PROBE 2: light object on white - erosion sweep")
print("=" * 60)
for obj_v in (255, 250, 245, 240, 235, 230, 220, 200):
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([W // 4, H // 4, 3 * W // 4, 3 * H // 4], fill=(obj_v, obj_v, obj_v, 255))
    analyze(f"obj grey={obj_v} on white", img, "white")

print("=" * 60)
print("PROBE 3: green object on green screen - despill/erosion sweep")
print("=" * 60)
for obj in [(40, 160, 60), (60, 200, 80), (100, 220, 120), (0, 255, 0), (50, 120, 50)]:
    img = Image.new("RGBA", (W, H), (20, 200, 30, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([W // 4, H // 4, 3 * W // 4, 3 * H // 4], fill=(*obj, 255))
    res, cm, tr = analyze(f"green obj {obj} on green screen", img, "keep obj")
    # measure despill color shift in center
    rgb = np.asarray(res.image.convert("RGBA"))[H // 2, W // 2, :3]
    print(f"      center RGB after = {tuple(int(v) for v in rgb)} (orig {obj})")

print("=" * 60)
print("PROBE 4: gradient grey - is content eaten / mode correct?")
print("=" * 60)
def make_gradient(w, h, c_top, c_bot, obj):
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(h):
        t = y / max(1, h - 1)
        for ch in range(3):
            arr[y, :, ch] = int(c_top[ch] * (1 - t) + c_bot[ch] * t)
        arr[y, :, 3] = 255
    img = Image.fromarray(arr, "RGBA")
    d = ImageDraw.Draw(img)
    d.ellipse([w // 4, h // 4, 3 * w // 4, 3 * h // 4], fill=(*obj, 255))
    return img

# grey gradient, red object - check residual bg fraction (should be ~0.8 if clean)
res, cm, tr = analyze("grad grey 230->170, red obj",
                      make_gradient(W, H, (230, 230, 230), (170, 170, 170), (200, 30, 30)), "?")
# How much background remains opaque? full bg is non-object area.
a = np.asarray(res.image.convert("RGBA"))[:, :, 3]
# object occupies center ellipse ~ pi/4 of half-area; bg should be transparent
print(f"      bg-leftover (opaque outside center quarter): inspect mid-band alpha")
print(f"      alpha row 10 (top, lighter bg)= {a[10, ::40].tolist()}")
print(f"      alpha row 245 (bottom, darker bg)= {a[245, ::40].tolist()}")

# grey gradient with a GREY object matching mid-gradient
res, cm, tr = analyze("grad grey 230->170, GREY obj=200",
                      make_gradient(W, H, (230, 230, 230), (170, 170, 170), (200, 200, 200)), "?")
print(f"      center_mean (grey obj should survive) = {cm:.0f}")

print("=" * 60)
print("PROBE 5: dark checker - object close to a tone")
print("=" * 60)
# dark checker 60/90, object grey 75 (between tones) -> eaten?
analyze("dark checker 60/90, obj grey=75",
        make_checker(W, H, (60, 60, 60), (90, 90, 90), 16, (75, 75, 75)), "eat obj?")
# dark checker, object dark grey 100 (close to 90)
analyze("dark checker 60/90, obj grey=100",
        make_checker(W, H, (60, 60, 60), (90, 90, 90), 16, (100, 100, 100)), "partial?")
# dark checker, object dark grey 120
analyze("dark checker 60/90, obj grey=120",
        make_checker(W, H, (60, 60, 60), (90, 90, 90), 16, (120, 120, 120)), "ok?")

print("=" * 60)
print("PROBE 6: tolerance/softness eating distant-but-similar objects")
print("=" * 60)
# white bg, object is light skin tone (240,220,200) - within tol+soft of white?
img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
d = ImageDraw.Draw(img)
d.ellipse([W // 4, H // 4, 3 * W // 4, 3 * H // 4], fill=(240, 220, 200, 255))
analyze("white bg, skin-tone obj (240,220,200)", img, "white, keep obj")
# dist from white = sqrt(15^2+35^2+55^2)=66.6 > tol+soft=56 -> should keep fully? check
print(f"      dist obj->white = {np.sqrt(15**2+35**2+55**2):.1f}, tol+soft=56")
