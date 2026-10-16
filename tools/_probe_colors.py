# -*- coding: utf-8 -*-
"""只读：打印争议站周围半径 R 内真实存在的颜色（排除背景 #F7F7F7 与黑字/白底），
回答"这站旁边到底画了哪几条线"。
"""
import json
from collections import Counter
import numpy as np
from PIL import Image

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
OFF = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126", encoding="utf-8"))["stations"]
lj = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))
_lines = lj["lines"] if isinstance(lj, dict) and "lines" in lj else lj
_iter = _lines if isinstance(_lines, list) else list(_lines.values())
COLOR = {str(l.get("id") or l.get("line_id")): l.get("color") for l in _iter}


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


REF = {lid: hex2rgb(c) for lid, c in COLOR.items()}

TARGETS = ["松岗", "朗下", "步涌", "国展", "国展北", "国展南", "会展城",
           "华新", "华强北", "黄木岗", "深圳湾公园", "机场北", "碧海湾",
           "坪山中心", "文化聚落", "中芯国际", "岗厦", "岗厦北"]

for nm in TARGETS:
    if nm not in OFF:
        print(nm, "官方备份缺")
        continue
    x, y = int(OFF[nm]["x"]), int(OFF[nm]["y"])
    R = 70
    sub = img[max(0, y - R):y + R, max(0, x - R):x + R].reshape(-1, 3)
    cnt = Counter(map(tuple, sub.tolist()))
    # 过滤背景与文字/黑灰
    hits = Counter()
    for (r, g, b), n in cnt.items():
        if abs(r - 247) + abs(g - 247) + abs(b - 247) <= 12:
            continue          # 背景
        if r < 90 and g < 90 and b < 90:
            continue          # 黑字
        if n < 25:
            continue
        best, bd = None, 10 ** 9
        for lid, (rr, gg, bb) in REF.items():
            d = abs(r - rr) + abs(g - gg) + abs(b - bb)
            if d < bd:
                bd, best = d, lid
        if bd <= 60:
            hits[best] += n
    desc = ", ".join(f"{k}({COLOR[k]})×{v}" for k, v in hits.most_common())
    print(f"{nm:6s} ({x},{y})  →  {desc or '无'}")
