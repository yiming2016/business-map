# -*- coding: utf-8 -*-
"""只读：把原图里所有"灰色虚线"（出站换乘通道）找出来，列出位置与长度。
颜色取实测的 #8B8B8C，容差 25（黑字 #231F20 距它 320，绝不会混进来）。
虚线由多个 11x12 的小方块组成 —— 先把小方块全捞出来，再按"相邻成串"合并。"""
import json
import math
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
t = np.array([0x8B, 0x8B, 0x8C], dtype=np.int16)
m = (np.abs(img - t).sum(axis=2) <= 25)
lab, n = ndimage.label(m, np.ones((3, 3)))
area = np.bincount(lab.ravel())
sl = ndimage.find_objects(lab)
blobs = []
for i, s in enumerate(sl, start=1):
    if s is None:
        continue
    a = int(area[i])
    if a < 60:
        continue
    h = s[0].stop - s[0].start
    w = s[1].stop - s[1].start
    if w > 60 or h > 60:          # 大块灰（电车线/文字底衬）不要
        continue
    blobs.append(((s[1].start + s[1].stop) / 2, (s[0].start + s[0].stop) / 2, w, h, a))
print("小方块 %d 个" % len(blobs))

# 成串合并：两个方块中心距 < 60 就连起来
par = list(range(len(blobs)))
def find(x):
    while par[x] != x:
        par[x] = par[par[x]]
        x = par[x]
    return x
def uni(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        par[rb] = ra
for i in range(len(blobs)):
    for j in range(i + 1, len(blobs)):
        if math.dist(blobs[i][:2], blobs[j][:2]) < 60:
            uni(i, j)
grp = {}
for i in range(len(blobs)):
    grp.setdefault(find(i), []).append(i)

st = json.load(open(SRC + "/data/stations.json", encoding="utf-8"))["stations"]
pts = [(nm, float(s["x"]), float(s["y"])) for nm, s in st.items() if s.get("x") is not None]
def near(x, y, r=150):
    b = sorted(((math.dist((sx, sy), (x, y)), nm) for nm, sx, sy in pts))[:3]
    return " / ".join(nm for d, nm in b if d < r)

print("\n成串后共 %d 条虚线：" % len(grp))
for k, idx in sorted(grp.items(), key=lambda kv: min(blobs[i][1] for i in kv[1])):
    xs = [blobs[i][0] for i in idx]
    ys = [blobs[i][1] for i in idx]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    print("  (%5.0f,%5.0f)–(%5.0f,%5.0f)  长 %4.0f  块数 %2d  附近: %s"
          % (x0, y0, x1, y1, math.hypot(x1 - x0, y1 - y0), len(idx), near(cx, cy)))
