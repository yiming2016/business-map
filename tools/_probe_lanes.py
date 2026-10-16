# -*- coding: utf-8 -*-
"""只读：打印某站周围的「彩色走廊」剖面，看清各条线各占哪条道。
用法: python tools/_probe_lanes.py <cx> <cy> [half]
"""
import sys
import json
from collections import Counter

import numpy as np
from PIL import Image

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(int)
LINES = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))["lines"]
ST = json.load(open(SRC + "/data/stations.json", encoding="utf-8"))["stations"]

COLORS = {}
for L in LINES:
    COLORS[tuple(int(L["color"][i:i + 2], 16) for i in (1, 3, 5))] = L["id"]


def name_of(c):
    best, bd = None, 1e9
    for col, lid in COLORS.items():
        d = sum(abs(c[i] - col[i]) for i in range(3))
        if d < bd:
            bd, best = d, lid
    return ("%s号线" % best if best and best.isdigit() else str(best)), bd


def runs_along(vals, colors, label, coords):
    """vals: 每个采样点的颜色；输出连续同色段。"""
    print("  [%s]" % label)
    prev = None
    segs = []
    for i, c in enumerate(colors):
        nm, d = name_of(c)
        # 只有饱和度够高、且能对上某条线（差<60）才算线
        sat = int(c.max()) - int(c.min())
        if d < 60 and sat > 40:
            k = nm
        elif max(c) < 110:
            k = "描边"
        else:
            k = "·"
        segs.append(k)
    i = 0
    while i < len(segs):
        j = i
        while j + 1 < len(segs) and segs[j + 1] == segs[i]:
            j += 1
        if segs[i] not in ("·",):
            c0, c1 = coords[i], coords[j]
            print("    %-10s %5d..%-5d  中位%5d  宽%3d" % (segs[i], c0, c1, (c0 + c1) // 2, c1 - c0 + 1))
        i = j + 1


cx, cy = int(sys.argv[1]), int(sys.argv[2])
half = int(sys.argv[3]) if len(sys.argv) > 3 else 200

print("=== 站中心 (%d,%d) ===" % (cx, cy))
for dy in (-45, 0, 45):
    y = cy + dy
    xs = list(range(cx - half, cx + half))
    cols = [img[y, x] for x in xs]
    runs_along(None, cols, "水平扫描 y=%d (dy=%+d)" % (y, dy), xs)
for dx in (-45, 0, 45):
    x = cx + dx
    ys = list(range(cy - half, cy + half))
    cols = [img[y, x] for y in ys]
    runs_along(None, cols, "垂直扫描 x=%d (dx=%+d)" % (x, dx), ys)
