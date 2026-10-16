# -*- coding: utf-8 -*-
"""只读：查任意像素点周围有哪些线色，并可给出该点是否落在某色走廊上。
用法：python tools/_probe_point.py x1,y1  x2,y2 ...
"""
import sys
import json
from collections import Counter
import numpy as np
from PIL import Image

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
lj = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))
_l = lj["lines"] if isinstance(lj, dict) and "lines" in lj else lj
_l = _l if isinstance(_l, list) else list(_l.values())
COLOR = {str(l.get("id") or l.get("line_id")): l.get("color") for l in _l}


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


REFS = {lid: hex2rgb(c) for lid, c in COLOR.items()}

for tok in sys.argv[1:]:
    x, y = (int(v) for v in tok.split(","))
    R = 16          # 只看紧贴圆点外圈，判断"这站压在什么色上"
    for R in (16, 30):
        sub = img[y - R:y + R, x - R:x + R].reshape(-1, 3)
        cnt = Counter(map(tuple, sub.tolist()))
        out = []
        for (r, g, b), k in cnt.items():
            if abs(r - 247) + abs(g - 247) + abs(b - 247) <= 12:
                continue
            if abs(r - 254) + abs(g - 254) + abs(b - 254) <= 12:
                continue
            if r < 90 and g < 90 and b < 90:
                continue
            if k < max(6, (2 * R) ** 2 * 0.004):
                continue
            best, bd = None, 10 ** 9
            for lid, (rr, gg, bb) in REFS.items():
                d = abs(r - rr) + abs(g - gg) + abs(b - bb)
                if d < bd:
                    bd, best = d, lid
            if bd <= 45:
                out.append((best, k, bd, (r, g, b)))
        agg = Counter()
        for lid, k, bd, rgb in out:
            agg[lid] += k
        print(f"({x},{y}) R={R:2d} → " + (", ".join(f"{lid}({COLOR[lid]})×{k}" for lid, k in agg.most_common()) or "只有白/背景"))
