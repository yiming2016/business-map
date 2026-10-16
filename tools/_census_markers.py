# -*- coding: utf-8 -*-
"""只读：全图站点圆点清点，与库中站对账。
输出：
  1) 图上有圆点、库里没有对应站的  ★（= 漏站）
  2) 库里有站、图上找不到圆点的    （= 坐标错/或站名错）
  3) 统计分布
用法：python tools/_census_markers.py
"""
import json
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
OFF = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126", encoding="utf-8"))["stations"]
H, W = img.shape[:2]

white = (np.abs(img[:, :, 0] - 254) + np.abs(img[:, :, 1] - 254) + np.abs(img[:, :, 2] - 254)) <= 12
white = ndimage.binary_erosion(white, np.ones((3, 3)))
lab, n = ndimage.label(white, np.ones((3, 3)))
print(f"白色连通块 {n} 个")
area = np.bincount(lab.ravel())

sl = ndimage.find_objects(lab)
cands = []
for i, s in enumerate(sl, start=1):
    if s is None:
        continue
    a = int(area[i])
    if a < 150:
        continue
    h = s[0].stop - s[0].start
    w = s[1].stop - s[1].start
    if not (14 <= w <= 140 and 14 <= h <= 140):
        continue
    if a / (w * h) < 0.55:
        continue
    sub = (lab[s] == i)
    yy, xx = np.nonzero(sub)
    cx = int(xx.mean()) + s[1].start
    cy = int(yy.mean()) + s[0].start
    cands.append((cx, cy, w, h, a))

print(f"形态像站点标记的圆点 {len(cands)} 个（库中站 {len(OFF)} 个）")
print(f"  其中 正圆(短边<30) {sum(1 for c in cands if min(c[2],c[3])<30)} 个，"
      f"药丸 {sum(1 for c in cands if min(c[2],c[3])>=30)} 个")

# 点对点匹配
used = set()
print("\n【1】图上有圆点、库里 45px 内没有对应站  ★ = 漏站候选")
miss_db = []
for cx, cy, w, h, a in sorted(cands, key=lambda t: (t[1], t[0])):
    best, bd = None, 10 ** 9
    for nm, s in OFF.items():
        d = ((s["x"] - cx) ** 2 + (s["y"] - cy) ** 2) ** 0.5
        if d < bd:
            bd, best = d, nm
    if bd >= 45:
        kind = "药丸" if min(w, h) >= 30 else "正圆"
        print(f"  ★ ({cx:5d},{cy:5d})  {w:3d}×{h:3d} {kind} 面积{a:5d}  (最近库站 {best} {bd:.0f}px)")
        miss_db.append((cx, cy, w, h))
    else:
        used.add(best)

print("\n【2】库里有站、图上 45px 内找不到圆点  (坐标可疑/站名可疑)")
miss_img = []
for nm, s in sorted(OFF.items()):
    if nm in used:
        continue
    best, bd = None, 10 ** 9
    for cx, cy, w, h, a in cands:
        d = ((s["x"] - cx) ** 2 + (s["y"] - cy) ** 2) ** 0.5
        if d < bd:
            bd, best = d, (cx, cy)
    if bd >= 45:
        print(f"  ? {nm:8s} 库坐标({s['x']:.0f},{s['y']:.0f})  最近圆点 {bd:.0f}px  @{best}")
        miss_img.append(nm)

print(f"\n汇总：漏站候选 {len(miss_db)} 个；库中缺对应圆点的站 {len(miss_img)} 个")
