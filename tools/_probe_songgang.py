# -*- coding: utf-8 -*-
"""只读探针：判定若干争议站是否真的落在某条线的走廊上（在原图官方像素系下）。
不写任何业务数据，只打印结论 + 存裁图供人眼复核。
"""
import json
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"

img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
OFF = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126", encoding="utf-8"))["stations"]
CUR = json.load(open(SRC + "/data/stations.json", encoding="utf-8"))["stations"]
lj = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))
_lines = lj["lines"] if isinstance(lj, dict) and "lines" in lj else lj
_iter = _lines if isinstance(_lines, list) else list(_lines.values())
COLOR = {str(l.get("id") or l.get("line_id")): l.get("color") for l in _iter}


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


_cache = {}


def mask_of(lid):
    if lid in _cache:
        return _cache[lid]
    r, g, b = hex2rgb(COLOR[lid])
    m = (np.abs(img[:, :, 0] - r) + np.abs(img[:, :, 1] - g) + np.abs(img[:, :, 2] - b)) <= 20
    _cache[lid + "_raw"] = m
    m = ndimage.binary_erosion(m, np.ones((3, 3)))
    _cache[lid] = m
    print(f"    [掩膜] {lid}号线 {COLOR[lid]}  原始 {int(_cache[lid+'_raw'].sum())} px → 腐蚀后 {int(m.sum())} px")
    return m


def probe(lid, name, rad=40, src=OFF):
    m = mask_of(lid)
    s = src[name]
    x, y = s["x"], s["y"]
    x0, y0 = max(0, int(x - rad)), max(0, int(y - rad))
    x1, y1 = min(img.shape[1], int(x + rad)), min(img.shape[0], int(y + rad))
    sub = m[y0:y1, x0:x1]
    ys, xs = np.nonzero(sub)
    if len(xs) == 0:
        return None
    d = np.hypot(xs + x0 - x, ys + y0 - y)
    i = d.argmin()
    return float(d[i]), (int(xs[i] + x0), int(ys[i] + y0))


def connected(lid, a, b, rad=40):
    m = mask_of(lid)
    lab, _ = ndimage.label(m, np.ones((3, 3)))
    pa, pb = probe(lid, a, rad), probe(lid, b, rad)
    if not pa or not pb:
        return None
    ca, cb = lab[pa[1][1], pa[1][0]], lab[pb[1][1], pb[1][0]]
    return (bool(ca == cb and ca > 0), pa[0], pb[0], int((lab == ca).sum()))


def block(title, names, lines):
    print("\n== " + title)
    for nm in names:
        if nm not in OFF:
            print(f"  {nm}：官方备份里没有")
            continue
        cur = CUR.get(nm)
        out = [f"官方坐标({OFF[nm]['x']:.0f},{OFF[nm]['y']:.0f})"]
        for lid in lines:
            p = probe(lid, nm)
            out.append(f"{lid}={p[0]:.1f}px" if p else f"{lid}=>40px")
        if cur:
            out.append(f"当前lines={cur['lines']}")
            out.append(f"偏移量={np.hypot(cur['x']-OFF[nm]['x'], cur['y']-OFF[nm]['y']):.0f}px")
        print("  " + nm + "  " + "  ".join(out))


block("1) 松岗（争议：是否 6/11/12 三线换乘）", ["松岗", "朗下", "步涌"], ["6", "11", "12"])
print("  12号线 松岗<->朗下 同分量:", connected("12", "松岗", "朗下"))
print("  12号线 朗下<->步涌 同分量:", connected("12", "朗下", "步涌"))

block("2) 华新（争议：3/7 换乘）", ["华新", "华强北", "黄木岗"], ["3", "7", "2"])
print("  7号线 华新<->华强北 同分量:", connected("7", "华新", "华强北"))
print("  7号线 华新<->黄木岗 同分量:", connected("7", "华新", "黄木岗"))

block("3) 国展片区（20号线色 #99DBDE）", ["国展", "国展北", "国展南", "会展城", "机场北"], ["12", "20", "11"])

block("4) 深圳湾公园（争议：是否 9/11）", ["深圳湾公园"], ["9", "11"])

block("5) 机场 / 福星（库中缺失站）", ["机场北", "碧海湾"], ["11", "20"])

block("6) 坪山云巴", ["坪山中心", "文化聚落", "中芯国际"], ["14", "坪山云巴"])
p = probe("坪山云巴", "文化聚落", rad=300)
print("  文化聚落 → 云巴灰线:", f"{p[0]:.1f}px" if p else "半径300内无")

print("\n== 7) 偏移总览（当前布局 vs 官方像素，抽样 30 站）")
import random
random.seed(7)
ds = []
for nm in random.sample(list(OFF.keys()), 30):
    if nm in CUR:
        ds.append(np.hypot(CUR[nm]["x"] - OFF[nm]["x"], CUR[nm]["y"] - OFF[nm]["y"]))
print(f"  抽样30站偏移：中位 {np.median(ds):.0f}px  最大 {max(ds):.0f}px")

base = Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")
CROPS = {
    "_q_songgang.png": (760, 1300, 1700, 2050),
    "_q_guozhan.png": (700, 2500, 1400, 3600),
    "_q_huaxin2.png": (3550, 4550, 3950, 5120),
}
for fn, (x0, y0, x1, y1) in CROPS.items():
    base.crop((x0, y0, x1, y1)).resize(((x1 - x0) // 2, (y1 - y0) // 2)).save(SRC + "/logs/" + fn)
    print("裁图:", fn, (x0, y0, x1, y1))
