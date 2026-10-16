# -*- coding: utf-8 -*-
"""只读：区域圆点清点 + 与库中站对账。
把某矩形区域内所有"站点白圆/药丸"检出，逐个匹配最近的库中站；
匹配不上的 = 图上有、库里没有的站。用法：python tools/_probe_region.py x0 y0 x1 y1
"""
import sys
import json
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
OFF = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126", encoding="utf-8"))["stations"]

x0, y0, x1, y1 = (int(v) for v in sys.argv[1:5])
sub = img[y0:y1, x0:x1]
white = (np.abs(sub[:, :, 0] - 254) + np.abs(sub[:, :, 1] - 254) + np.abs(sub[:, :, 2] - 254)) <= 10
white = ndimage.binary_erosion(white, np.ones((3, 3)))
lab, n = ndimage.label(white, np.ones((3, 3)))
found = []
for i in range(1, n + 1):
    m = lab == i
    a = int(m.sum())
    if a < 150:
        continue
    yy, xx = np.nonzero(m)
    w = xx.max() - xx.min() + 1
    h = yy.max() - yy.min() + 1
    if not (14 <= w <= 130 and 14 <= h <= 130):
        continue
    if a / (w * h) < 0.55:      # 必须够"实"（避免把白描边带、白标签背景当真圆）
        continue
    cx, cy = int(xx.mean()) + x0, int(yy.mean()) + y0
    found.append((cx, cy, w, h, a))

print(f"区域 x[{x0},{x1}) y[{y0},{y1})  检出圆点 {len(found)} 个（库中该区域站 "
      f"{sum(1 for s in OFF.values() if x0<=s['x']<x1 and y0<=s['y']<y1)} 个）")
found.sort(key=lambda t: (t[1], t[0]))
for cx, cy, w, h, a in found:
    best, bd = None, 10 ** 9
    for nm, s in OFF.items():
        d = ((s["x"] - cx) ** 2 + (s["y"] - cy) ** 2) ** 0.5
        if d < bd:
            bd, best = d, nm
    tag = f"库中最近站: {best} ({bd:.0f}px)" if bd < 45 else "★ 库里没有对应站"
    kind = "药丸" if (w >= 30 or h >= 30) else "正圆"
    print(f"  ({cx:5d},{cy:5d})  {w:3d}×{h:3d}  {kind}  面积{a:5d}   {tag}")
