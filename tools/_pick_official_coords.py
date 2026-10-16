# -*- coding: utf-8 -*-
"""只读：判定哪一份备份才是"真正贴着原图圆点"的坐标。
做法：先从原图检出所有圆点，再对每份备份算"每个站到最近圆点的距离"，比中位数/p90。
离得最近的那份 = 真值。
"""
import glob
import json
import os
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
white = (np.abs(img[:, :, 0] - 254) + np.abs(img[:, :, 1] - 254) + np.abs(img[:, :, 2] - 254)) <= 12
white = ndimage.binary_erosion(white, np.ones((3, 3)))
lab, n = ndimage.label(white, np.ones((3, 3)))
area = np.bincount(lab.ravel())
sl = ndimage.find_objects(lab)
pts = []
for i, s in enumerate(sl, start=1):
    if s is None:
        continue
    a = int(area[i])
    if a < 150:
        continue
    h, w = s[0].stop - s[0].start, s[1].stop - s[1].start
    if not (14 <= w <= 140 and 14 <= h <= 140):
        continue
    if a / (w * h) < 0.55:
        continue
    sub = (lab[s] == i)
    yy, xx = np.nonzero(sub)
    pts.append((int(xx.mean()) + s[1].start, int(yy.mean()) + s[0].start))
pts = np.array(pts, dtype=float)
print(f"圆点 {len(pts)} 个")

files = sorted(glob.glob(SRC + "/data/stations.json*")) + sorted(glob.glob(SRC + "/data/_trial.json"))
print(f"{'文件':52s} {'站数':>4s} {'中位':>7s} {'p90':>7s} {'>45px':>6s} {'>100px':>7s}")
best = []
for f in files:
    try:
        d = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    st = d.get("stations") if isinstance(d, dict) else None
    if not isinstance(st, dict) or not st:
        continue
    arr = np.array([[s["x"], s["y"]] for s in st.values()], dtype=float)
    if arr.size == 0:
        continue
    dd = np.sqrt(((arr[:, None, :] - pts[None, :, :]) ** 2).sum(-1)).min(1)
    name = os.path.basename(f)
    print(f"{name:52s} {len(arr):4d} {np.median(dd):7.1f} {np.percentile(dd,90):7.1f} "
          f"{int((dd>45).sum()):6d} {int((dd>100).sum()):7d}")
    best.append((np.median(dd), name))
best.sort()
print("\n按中位距离排序前三：", [b[1] for b in best[:3]])
