"""Deep-dive: the auto-mode 'single logical object' failures and the
_merge_fragments 12%/max_gap heuristics. We quantify when auto over-splits
a wordmark / detached-part logo, and when merge_distance can or cannot fix it.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from assetforge.core import detect


def canvas(w, h):
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def R(im, b, col=(255, 255, 255, 255)):
    ImageDraw.Draw(im).rectangle(b, fill=col)


def E(im, b, col=(0, 200, 120, 255)):
    ImageDraw.Draw(im).ellipse(b, fill=col)


def show(name, im, **kw):
    md = kw.pop("merge_distance", 0)
    mode = kw.pop("mode", "auto")
    boxes = detect.split_objects(im, mode=mode, merge_distance=md, **kw)
    print(f"  {name:42s} mode={mode:7s} md={md:<4} -> {len(boxes)}")
    return boxes


print("=" * 78)
print("A) WORDMARK in AUTO across merge_distance sweep (expect 1)")
print("=" * 78)
im = canvas(600, 160)
d = ImageDraw.Draw(im)
try:
    font = ImageFont.truetype("arial.ttf", 90)
except Exception:
    font = ImageFont.load_default()
d.text((20, 20), "BRAND", fill=(255, 255, 255, 255), font=font)
for md in (0, 5, 10, 15, 20, 25, 30, 40):
    show(f"BRAND md={md}", im, mode="auto", merge_distance=md)

print()
print("=" * 78)
print("B) DETACHED-PART LOGO in AUTO across merge_distance (expect 1)")
print("=" * 78)
im = canvas(400, 400)
E(im, (120, 150, 280, 310))          # main
E(im, (185, 60, 215, 90))            # i-dot, gap ~60px above
R(im, (60, 90, 75, 105), (255, 255, 0, 255))   # sparkle
R(im, (330, 100, 342, 112), (255, 255, 0, 255))
for md in (0, 5, 10, 20, 40, 60, 80):
    show(f"logo md={md}", im, mode="auto", merge_distance=md)

print()
print("=" * 78)
print("C) _merge_fragments 12%-of-max RULE: medium objects swallowed?")
print("    3 separate squares of DECREASING size, far apart. Expect 3.")
print("=" * 78)
# largest 300x300 area=90000; 12% = 10800 => side ~104. medium 100x100=10000<10800
im = canvas(900, 360)
R(im, (10, 30, 310, 330), (255, 0, 0, 255))     # 300x300 area 90000
R(im, (360, 130, 460, 230), (0, 255, 0, 255))   # 100x100 area 10000 (<12%!)
R(im, (520, 155, 600, 235), (0, 0, 255, 255))   # 80x80 area 6400  (<12%)
b = show("3 decreasing far-apart", im, mode="objects")
print(f"     boxes={b}")

print()
print("=" * 78)
print("D) 12%-rule + GAP: medium object NEAR the huge one gets ABSORBED")
print("    huge square + a real separate medium icon placed within max_gap.")
print("=" * 78)
# max_gap = max(3, round(min(H,W)*0.02)). For 360 tall -> 0.02*360=7.2 ->7
# Place medium 8px away (just over). Then 5px away (under) to show absorb.
for gap in (5, 7, 8, 12, 20):
    im = canvas(900, 360)
    R(im, (10, 30, 310, 330), (255, 0, 0, 255))   # huge area 90000
    x0 = 310 + gap
    R(im, (x0, 130, x0 + 90, 230), (0, 255, 0, 255))  # medium 90x100=9000 <12%
    b = detect.split_objects(im, mode="objects")
    print(f"  medium gap={gap:3d}px from huge -> {len(b)} objects (expect 2)  {b if len(b)!=2 else ''}")

print()
print("=" * 78)
print("E) STANDALONE small icons (area<12% of biggest AND >min_area):")
print("    many small icons + one big. small not near big -> kept? count.")
print("=" * 78)
im = canvas(1000, 400)
R(im, (10, 20, 360, 380), (255, 128, 0, 255))   # big area ~126000
# 8 small icons 50x50=2500 area (<12% of 126000=15120), spread far from big & each other
small_n = 0
for i in range(8):
    x = 420 + (i % 4) * 130
    y = 40 + (i // 4) * 180
    R(im, (x, y, x + 50, y + 50), (0, 128, 255, 255))
    small_n += 1
b = detect.split_objects(im, mode="objects", min_area=64)
print(f"  big + {small_n} small far icons -> {len(b)} (expect {1+small_n})")
if len(b) != 1 + small_n:
    print(f"     boxes={b}")

print()
print("=" * 78)
print("F) min_area filtering of legit small icons (default min_area=64)")
print("    icons of 6x6=36px < 64 -> dropped silently.")
print("=" * 78)
im = canvas(400, 400)
for i in range(9):
    x = 40 + (i % 3) * 120; y = 40 + (i // 3) * 120
    R(im, (x, y, x + 6, y + 6), (255, 0, 0, 255))  # 6x6 = 36 area
b = detect.split_objects(im, mode="objects", min_area=64)
print(f"  9 icons of 6x6 (area 36) min_area=64 -> {len(b)} (expect 9)")
b2 = detect.split_objects(im, mode="objects", min_area=16)
print(f"  same with min_area=16 -> {len(b2)}")
