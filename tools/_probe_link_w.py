# -*- coding: utf-8 -*-
"""只读：量原图"换乘连接线"的宽度（横截面字符画），与我们的 SCENE_DASH_W 对照。
用法: python tools/_probe_link_w.py <cx> <cy> <half> <axis>
  axis=x 表示沿水平方向扫一行（量竖直走向的线宽）
"""
import sys
from PIL import Image

img = Image.open("C:/software/subway/源码/assets/shenzhen_metro.png").convert("RGB")
cx, cy, half = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
axis = (sys.argv[4] if len(sys.argv) > 4 else "x")

def is_grey(p):
    r, g, b = p
    return abs(r-g) < 14 and abs(g-b) < 14 and 90 <= r <= 200

runs = []
for d in range(-half, half+1):
    if axis == "x":
        pts = [(cx+d, cy)]
    else:
        pts = [(cx, cy+d)]
    on = sum(1 for p in pts if is_grey(img.getpixel(p)))
    runs.append("#" if on else ".")

print("".join(runs))
# 连续宽度
best, cur = 0, 0
for ch in runs:
    cur = cur+1 if ch == "#" else 0
    best = max(best, cur)
print("max_grey_run =", best)
