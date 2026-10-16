# -*- coding: utf-8 -*-
"""只读：沿指定走廊检测"站点白圆标记"，回答"图上这两站之间到底画了几个站"。
标记定义：内部 #FEFEFE 的白色实心块，外圈有深灰描边，面积/尺寸在合理区间。
"""
import json
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
OFF = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126", encoding="utf-8"))["stations"]

# 站点白圆内部
white = (np.abs(img[:, :, 0] - 254) + np.abs(img[:, :, 1] - 254) + np.abs(img[:, :, 2] - 254)) <= 10
white = ndimage.binary_erosion(white, np.ones((3, 3)))
lab, n = ndimage.label(white, np.ones((3, 3)))
objs = ndimage.find_objects(lab)
sizes = np.bincount(lab.ravel())

print(f"白色块总数 {n}，下面筛出尺寸像站点圆点的：")

cands = []
for i, sl in enumerate(objs, start=1):
    if sl is None:
        continue
    h = sl[0].stop - sl[0].start
    w = sl[1].stop - sl[1].start
    a = int(sizes[i])
    if a < 120:
        continue
    if not (12 <= w <= 120 and 12 <= h <= 120):
        continue
    cy, cx = ndimage.center_of_mass(lab == i)
    cands.append((int(cx), int(cy), w, h, a))

print(f"  候选 {len(cands)} 个")


def markers_between(a, b, tol=60, box=140):
    """在 a→b 线段附近、沿线方向位于两端之间(含外扩 tol)的标记"""
    ax, ay = OFF[a]["x"], OFF[a]["y"]
    bx, by = OFF[b]["x"], OFF[b]["y"]
    vx, vy = bx - ax, by - ay
    L = np.hypot(vx, vy)
    ux, uy = vx / L, vy / L
    out = []
    for cx, cy, w, h, ar in cands:
        px, py = cx - ax, cy - ay
        t = px * ux + py * uy
        s = abs(px * (-uy) + py * ux)
        if -tol <= t <= L + tol and s <= box:
            out.append((round(t), round(s), cx, cy, w, h))
    out.sort()
    return out, L


def between(a, b):
    ms, L = markers_between(a, b)
    print(f"\n{a} → {b}  (图上距离 {L:.0f}px)  沿线标记 {len(ms)} 个：")
    for t, s, cx, cy, w, h in ms:
        print(f"    t={t:5d}px  离中心线 {s:3d}px  位置({cx},{cy})  尺寸 {w}×{h}")


between("机场北", "碧海湾")
between("岗厦北", "华强南")
between("机场北", "会展城")
between("文化聚落", "中芯国际")
