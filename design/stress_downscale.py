"""Pinpoint the hard-coded max_gap absorb behavior and downscale (720px NEAREST)
bridging/breaking on large dense layouts. These are independent of merge_distance.
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
print("G) HARD-CODED absorb: small real icon next to big logo is eaten")
print("   even at merge_distance=0 (default). Sweep image size to show the")
print("   max_gap=round(min(H,W)*0.02) threshold scales with image.")
print("=" * 78)
for S in (300, 600, 1200, 2400):
    # big square left half, small 5%-side icon to its right with a fixed 6px gap
    im = canvas(S, S)
    big = int(S * 0.45)
    R(im, (10, 10, 10 + big, 10 + big), (255, 0, 0, 255))
    small = max(20, int(S * 0.05))
    gap = 6
    x0 = 10 + big + gap
    R(im, (x0, S // 2, x0 + small, S // 2 + small), (0, 0, 255, 255))
    max_gap = max(3, round(min(S, S) * 0.02))
    n = len(detect.split_objects(im, mode="objects"))
    print(f"  S={S:5d} small={small} gap={gap}px  max_gap={max_gap:3d}  -> {n} (expect 2)"
          f"{'  ABSORBED' if n < 2 else ''}")

print()
print("=" * 78)
print("H) DOWNSCALE NEAREST bridging: dense grid on a LARGE canvas (>720)")
print("   tiny gaps collapse after downscale to 720 -> components merge.")
print("=" * 78)
# 20x20 grid of 90px tiles, 6px gaps -> canvas ~1920px. After /720 scale 0.375,
# a 6px gap -> 2.25px, NEAREST may close it.
for (tiles, tile, gap) in [(8, 90, 6), (12, 90, 6), (16, 110, 5), (20, 90, 4)]:
    side = tiles * (tile + gap) + gap
    im = canvas(side, side)
    n_true = 0
    for r in range(tiles):
        for c in range(tiles):
            x = gap + c * (tile + gap); y = gap + r * (tile + gap)
            R(im, (x, y, x + tile, y + tile), (200, 50, 50, 255))
            n_true += 1
    got = len(detect.split_objects(im, mode="objects", min_area=16))
    eff_gap = gap * (720 / side)
    print(f"  {tiles}x{tile}px gap{gap} side={side:5d} (eff_gap@720={eff_gap:.2f}px) "
          f"-> {got} (expect {n_true}){'  UNDER' if got < n_true else ''}")

print()
print("=" * 78)
print("I) DOWNSCALE breaking: thin-stroke connected shape on large canvas")
print("   a single shape with 1-2px connecting strokes can DISCONNECT after")
print("   downscale -> over-split a single object.")
print("=" * 78)
# Two big blobs joined by a 2px bridge on a 2000px canvas
im = canvas(2000, 600)
R(im, (50, 100, 850, 500), (0, 150, 0, 255))     # blob A
R(im, (1150, 100, 1950, 500), (0, 150, 0, 255))  # blob B
R(im, (850, 295, 1150, 305), (0, 150, 0, 255))   # 10px-tall bridge -> /3.3 = 3px
got = len(detect.split_objects(im, mode="auto"))
print(f"  2 blobs + 10px bridge (single shape) auto -> {got} (expect 1)"
      f"{'  SPLIT' if got != 1 else ''}")
im = canvas(2000, 600)
R(im, (50, 100, 850, 500), (0, 150, 0, 255))
R(im, (1150, 100, 1950, 500), (0, 150, 0, 255))
R(im, (850, 299, 1150, 301), (0, 150, 0, 255))   # 2px bridge -> /3.3 < 1px
got = len(detect.split_objects(im, mode="auto"))
print(f"  2 blobs + 2px bridge  (single shape) auto -> {got} (expect 1)"
      f"{'  SPLIT' if got != 1 else ''}")

print()
print("=" * 78)
print("J) The 12% rule eats a MEDIUM object regardless of gap when it is")
print("   the ONLY other shape and far below 12% threshold but is real.")
print("   (already separate -> kept as standalone if a>=min_area).")
print("   Confirm: medium between 0.5%..12% and within max_gap of big = eaten")
print("=" * 78)
im = canvas(1000, 1000)
R(im, (10, 10, 910, 910), (255, 0, 0, 255))       # huge area 810000
# medium 80x80 area=6400 (<0.8% -> well under 12%), 5px gap from huge corner
R(im, (915, 10, 995, 90), (0, 0, 255, 255))
b = detect.split_objects(im, mode="objects")
print(f"  huge + medium(6400px, gap5) -> {len(b)} (expect 2)  {b if len(b)<2 else ''}")
