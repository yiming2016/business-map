# -*- coding: utf-8 -*-
"""阶段1（只读）：按原图圆点全量重取站点坐标。

思路：
  1) 从原图检出所有"站点白圆/药丸"（连通域 + 形态过滤）→ 候选锚点
  2) 站点表 381 站 ↔ 候选锚点 做 **匈牙利一对一指派**（代价=距离）
     —— 不用最近邻，避免密集区互相抢同一个圆点
  3) 每个站顺带算出：圆点形态（正圆/药丸）、该圆点到本站各条线走廊的距离（交叉校验）
  4) 输出 logs/重取坐标_结果.md + logs/_resnap.json，**不写业务数据**

用法：python tools/_resnap_official.py
"""
import json
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.optimize import linear_sum_assignment

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
ST = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126", encoding="utf-8"))["stations"]
lj = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))
_l = lj["lines"] if isinstance(lj, dict) and "lines" in lj else lj
_l = _l if isinstance(_l, list) else list(_l.values())
COLOR = {str(l.get("id") or l.get("line_id")): l.get("color") for l in _l}
ORDER = {str(l.get("id") or l.get("line_id")): (l.get("stations") or l.get("order") or []) for l in _l}


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------- 1) 检出圆点 ----------
white = (np.abs(img[:, :, 0] - 254) + np.abs(img[:, :, 1] - 254) + np.abs(img[:, :, 2] - 254)) <= 12
white = ndimage.binary_erosion(white, np.ones((3, 3)))
lab, n = ndimage.label(white, np.ones((3, 3)))
area = np.bincount(lab.ravel())
sl = ndimage.find_objects(lab)
circ = []
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
    sub = lab[s] == i
    yy, xx = np.nonzero(sub)
    circ.append({
        "cx": int(xx.mean()) + s[1].start, "cy": int(yy.mean()) + s[0].start,
        "w": w, "h": h, "area": a,
        "x0": s[1].start, "y0": s[0].start, "x1": s[1].stop, "y1": s[0].stop,
    })
print(f"候选圆点 {len(circ)} 个 / 站点表 {len(ST)} 站")

# ---------- 2) 各线走廊距离场 ----------
dist_field = {}
for lid, c in COLOR.items():
    r, g, b = hex2rgb(c)
    m = (np.abs(img[:, :, 0] - r) + np.abs(img[:, :, 1] - g) + np.abs(img[:, :, 2] - b)) <= 20
    m = ndimage.binary_erosion(m, np.ones((3, 3)))
    dist_field[lid] = ndimage.distance_transform_edt(~m)
    print(f"  走廊场 {lid}({c}) 就绪")


def on_line(c, lid):
    """圆点到该线走廊的距离：中心距离 与 bbox 相交 取小（药丸中心天然不贴线 → 用 bbox）"""
    d_ctr = dist_field[lid][c["cy"], c["cx"]]
    x0 = max(0, c["x0"] - 3); y0 = max(0, c["y0"] - 3)
    x1 = min(img.shape[1], c["x1"] + 3); y1 = min(img.shape[0], c["y1"] + 3)
    d_bbox = float(dist_field[lid][y0:y1, x0:x1].min())
    return min(d_ctr, d_bbox), d_ctr, d_bbox


# ---------- 3) 匈牙利一对一指派 ----------
names = list(ST.keys())
P = np.array([[ST[k]["x"], ST[k]["y"]] for k in names], dtype=float)
C = np.array([[c["cx"], c["cy"]] for c in circ], dtype=float)
cost = np.sqrt(((P[:, None, :] - C[None, :, :]) ** 2).sum(-1))
cost = np.where(cost > 400, 100000.0, cost)          # 超远基本禁止
row, col = linear_sum_assignment(cost)
assert len(set(col)) == len(col), "指派不是一对一"

res = {}
for r, c in zip(row, col):
    nm = names[r]
    d = float(np.hypot(P[r, 0] - C[c, 0], P[r, 1] - C[c, 1]))
    res[nm] = {"old": [round(P[r, 0], 1), round(P[r, 1], 1)],
               "new": [round(C[c, 0], 1), round(C[c, 1], 1)],
               "move": round(d, 1), "circ": circ[c]}
print(f"指派完成；位移 中位 {np.median([v['move'] for v in res.values()]):.1f}px，"
      f"最大 {max(v['move'] for v in res.values()):.1f}px")

# ---------- 4) 输出 ----------
out = []
out.append("# 阶段1：按原图圆点重取的站点坐标（只读，未写入业务数据）\n")
out.append("口径：原图白圆/药丸连通域 → 匈牙利一对一指派到 381 站。\n")
out.append("「贴线」列：圆点（含 bbox）到该线走廊的最小距离，≤22px 记 ✅。\n")
big = [(nm, v) for nm, v in res.items() if v["move"] > 45]
out.append(f"\n位移 >45px 的站：{len(big)} 个（中位位移 "
           f"{np.median([v['move'] for v in res.values()]):.1f}px）\n")

for lid in COLOR:
    seq = ORDER.get(lid) or []
    if not seq:
        continue
    out.append(f"\n## {lid}号线（{COLOR[lid]}） {len(seq)} 站\n")
    out.append("| # | 站名 | 旧坐标 | 新坐标 | 位移 | 圆点 | 形态 | 贴线 |\n|---|---|---|---|---|---|---|---|")
    for i, nm in enumerate(seq, 1):
        v = res.get(nm)
        if not v:
            out.append(f"| {i} | {nm} | — | 未定位 | — | — | — | — |")
            continue
        c = v["circ"]
        kind = "药丸" if min(c["w"], c["h"]) >= 30 else "正圆"
        dmin, _, _ = on_line(c, lid)
        flag = "✅" if dmin <= 22 else f"⚠️{dmin:.0f}"
        out.append(f"| {i} | {nm} | ({v['old'][0]:.0f},{v['old'][1]:.0f}) | "
                   f"({v['new'][0]:.0f},{v['new'][1]:.0f}) | {v['move']:.0f}px | "
                   f"{c['w']}×{c['h']} | {kind} | {flag} |")

p = SRC + "/logs/重取坐标_结果.md"
open(p, "w", encoding="utf-8").write("\n".join(out))
print("已写出", p)

json.dump({k: {"old": v["old"], "new": v["new"], "move": v["move"]} for k, v in res.items()},
          open(SRC + "/logs/_resnap.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已写出 logs/_resnap.json")
