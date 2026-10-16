# -*- coding: utf-8 -*-
"""只算不写：把站点位置"吸到它所屬线路走廊的交点/中线"上。
换乘站 = 几条线走廊的交点；单线站 = 走廊中线。
用来验证/修正用户说的"往左下一点才居中"这类偏移。
用法：python tools/_snap_to_corridor.py 站名1 站名2 ...
"""
import json
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
ST = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126", encoding="utf-8"))["stations"]
FIN = json.load(open(SRC + "/logs/_final_coords.json", encoding="utf-8"))
lj = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))
_l = lj["lines"] if isinstance(lj, dict) and "lines" in lj else lj
_l = _l if isinstance(_l, list) else list(_l.values())
COLOR = {str(l.get("id") or l.get("line_id")): l.get("color") for l in _l}
COLOR.update({"4": "#E71615", "11": "#6D2041"})
FROZEN = {"坪山云巴", "有轨电车", "有轨电车支线"}


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


_cache = {}


def df_of(lid):
    if lid in _cache:
        return _cache[lid]
    r, g, b = hex2rgb(COLOR[lid])
    m = (np.abs(img[:, :, 0] - r) + np.abs(img[:, :, 1] - g) + np.abs(img[:, :, 2] - b)) <= 20
    f = ndimage.distance_transform_edt(~ndimage.binary_erosion(m, np.ones((3, 3))))
    _cache[lid] = f
    return f


def snap(nm, half=140, step=4):
    s = ST[nm]
    lids = [l for l in s["lines"] if l not in FROZEN]
    if not lids:
        return None
    px, py = FIN["final"].get(nm) or (s["x"], s["y"])
    H, W = img.shape[:2]
    x0 = max(0, int(px - half)); x1 = min(W, int(px + half))
    y0 = max(0, int(py - half)); y1 = min(H, int(py + half))
    fields = [df_of(l)[y0:y1, x0:x1] for l in lids]
    acc = np.zeros_like(fields[0])
    for f in fields:
        acc += f * f                      # 平方和：惩罚"离某条线特别远"
    iy, ix = np.unravel_index(int(np.argmin(acc)), acc.shape)
    bx, by = x0 + int(ix), y0 + int(iy)
    return (bx, by), (px, py), [round(float(fields[k][iy, ix]), 1) for k in range(len(lids))], lids


def dirs(dx, dy):
    o = []
    if dx < -6: o.append("左")
    if dx > 6: o.append("右")
    if dy < -6: o.append("上")
    if dy > 6: o.append("下")
    return "".join(o) or "原位"


for nm in sys.argv[1:]:
    r = snap(nm)
    if r is None:
        print(f"{nm}: 冻结/无线"); continue
    (bx, by), (px, py), ds, lids = r
    print(f"{nm:8s} ({px:.0f},{py:.0f}) → ({bx},{by})   "
          f"移动({bx - px:+.0f},{by - py:+.0f}) {dirs(bx - px, by - py)}   "
          f"离各线 {'/'.join(lids)} = {ds}")
