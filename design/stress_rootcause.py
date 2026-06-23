"""Confirm root causes precisely + test grid mode + realistic sheets.
"""
from __future__ import annotations
import numpy as np
from PIL import Image, ImageDraw
from assetforge.core import detect


def canvas(w, h):
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def R(im, b, col=(255, 255, 255, 255)):
    ImageDraw.Draw(im).rectangle(b, fill=col)


print("=" * 78)
print("K) ABSORB threshold sweep — huge + 1 medium(6400px), vary diag gap.")
print("   max_gap for 1000px img = round(1000*0.02)=20. So gap<=20 -> eaten.")
print("=" * 78)
for gap in (3, 5, 10, 18, 20, 22, 25, 30):
    im = canvas(1000, 1000)
    R(im, (10, 10, 910, 910), (255, 0, 0, 255))     # huge
    x0 = 910 + gap
    R(im, (x0, 400, x0 + 80, 480), (0, 0, 255, 255))  # medium aligned (pure horiz gap)
    n = len(detect.split_objects(im, mode="objects"))
    print(f"  horiz gap={gap:3d}px (max_gap=20) -> {n} (expect 2){'  <-EATEN' if n<2 else ''}")

print()
print("=" * 78)
print("L) Same but medium is itself >=12% — never eaten regardless of gap")
print("=" * 78)
for gap in (3, 5, 10):
    im = canvas(1000, 1000)
    R(im, (10, 10, 910, 910), (255, 0, 0, 255))      # huge 810000
    x0 = 910 + gap
    R(im, (x0, 200, x0 + 80, 600), (0, 0, 255, 255)) # 80x400=32000 -> ~4% still <12
    # bump to >12%: 80x980 -> would overflow; use 89x980
    n = len(detect.split_objects(im, mode="objects"))
    print(f"  medium 32000px (4%) gap={gap} -> {n} (12% of 810000 = {0.12*810000:.0f})")

print()
print("=" * 78)
print("M) min_area default=64 silently drops small icons (auto + objects)")
print("=" * 78)
for side in (4, 6, 7, 8, 9, 10):
    im = canvas(400, 400)
    cnt = 0
    for i in range(9):
        x = 40 + (i % 3) * 120; y = 40 + (i // 3) * 120
        R(im, (x, y, x + side, y + side), (255, 0, 0, 255))
        cnt += 1
    area = side * side
    no = len(detect.split_objects(im, mode="objects", min_area=64))
    na = len(detect.split_objects(im, mode="auto", min_area=64))
    print(f"  9 icons {side}x{side}(area={area:3d}) min_area=64 -> objects={no} auto={na} (expect 9)")

print()
print("=" * 78)
print("N) GRID mode sanity: spritesheet 4x4, grid mode vs objects")
print("=" * 78)
im = canvas(420, 420)
for r in range(4):
    for c in range(4):
        x = 5 + c * 105; y = 5 + r * 105
        R(im, (x + 10, y + 10, x + 90, y + 90), (0, 150, 200, 255))
gb = detect.split_objects(im, mode="grid", grid_rows=4, grid_cols=4)
ob = detect.split_objects(im, mode="objects")
print(f"  4x4 spritesheet grid->{len(gb)} objects->{len(ob)} (expect 16/16)")
# grid with WRONG dims (user supplies 3x3 for a 4x4 sheet)
gb2 = detect.split_objects(im, mode="grid", grid_rows=3, grid_cols=3)
print(f"  4x4 sheet but grid_rows=3,cols=3 -> {len(gb2)} cells (cells may cut objects)")

print()
print("=" * 78)
print("O) REALISTIC: wordmark + emblem on one sheet (the stated typical case)")
print("   'LOGO' text-like 4 bars on left + 1 emblem square on right.")
print("   Intended: auto should give a sensible split. md=0 default.")
print("=" * 78)
im = canvas(700, 200)
# 4 letter-like bars (a wordmark) left
for i in range(4):
    x = 20 + i * 60
    R(im, (x, 50, x + 40, 150), (255, 255, 255, 255))
# emblem far right
R(im, (520, 50, 640, 170), (0, 200, 120, 255))
for md in (0, 10, 20, 30):
    n = len(detect.split_objects(im, mode="auto", merge_distance=md))
    print(f"  wordmark(4 bars)+emblem md={md} auto -> {n}  "
          f"(want 2: one wordmark + one emblem)")

print()
print("=" * 78)
print("P) AUTO collapses to 1 ONLY if components==1. 2 far apart logos =2 (good)")
print("   But wordmark of 5 letters in auto = 5 (bad). Show the inconsistency.")
print("=" * 78)
im = canvas(700, 300)
R(im, (20, 20, 320, 280), (255, 0, 0, 255))
R(im, (380, 20, 680, 280), (0, 0, 255, 255))
print(f"  2 separate logos auto -> {len(detect.split_objects(im, mode='auto'))} (expect 2, good)")
