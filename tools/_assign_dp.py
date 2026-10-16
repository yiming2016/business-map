# -*- coding: utf-8 -*-
"""门2 定稿（只读）：站序做裁判的动态规划认领。

为什么需要它：
  - 保守吸附（靠旧坐标）在旧坐标漂了的站上会错
  - OCR 认领（靠站名文字）在密集区把相邻两站认反（车公庙/香蜜湖 互换）
  ⇒ 用 **线路站序**（已验证正确）当裁判：沿站序做 DP，
     代价 = 到锚点(OCR框/旧坐标)的距离 + 0.35 × 与上一站的跳距
     这样既贴锚点，又保证沿线走是"一步一步走过去"而不是乱跳。

冻结：坪山云巴 / 有轨电车 / 有轨电车支线（原图中间站无圆点，保持现状）

产物：logs/_assign_dp.json
"""
import json
import difflib
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
FROZEN = {"坪山云巴", "有轨电车", "有轨电车支线"}
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
ST = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126", encoding="utf-8"))["stations"]
OCR = json.load(open(SRC + "/data/ocr_labels.json", encoding="utf-8"))
lj = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))
_l = lj["lines"] if isinstance(lj, dict) and "lines" in lj else lj
_l = _l if isinstance(_l, list) else list(_l.values())
COLOR = {str(l.get("id") or l.get("line_id")): l.get("color") for l in _l}
COLOR.update({"4": "#E71615", "11": "#6D2041"})
ORDER = {str(l.get("id") or l.get("line_id")): (l.get("stations") or l.get("order") or []) for l in _l}


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def norm(s):
    return "".join(ch for ch in s.strip() if ch not in " 　:：·.、-—")


DF = {}
for lid, c in COLOR.items():
    r, g, b = hex2rgb(c)
    m = (np.abs(img[:, :, 0] - r) + np.abs(img[:, :, 1] - g) + np.abs(img[:, :, 2] - b)) <= 20
    DF[lid] = ndimage.distance_transform_edt(~ndimage.binary_erosion(m, np.ones((3, 3))))

xs = [s["x"] for s in ST.values()]; ys = [s["y"] for s in ST.values()]
BX = (min(xs) - 250, max(xs) + 250, min(ys) - 250, max(ys) + 250)
white = (np.abs(img[:, :, 0] - 254) + np.abs(img[:, :, 1] - 254) + np.abs(img[:, :, 2] - 254)) <= 12
white = ndimage.binary_erosion(white, np.ones((3, 3)))
lab, n = ndimage.label(white, np.ones((3, 3)))
area = np.bincount(lab.ravel()); sl = ndimage.find_objects(lab)
circ = []
for i, s in enumerate(sl, start=1):
    if s is None:
        continue
    a = int(area[i])
    if a < 150:
        continue
    h, w = s[0].stop - s[0].start, s[1].stop - s[1].start
    if not (14 <= w <= 140 and 14 <= h <= 140) or a / (w * h) < 0.55:
        continue
    sub = lab[s] == i
    yy, xx = np.nonzero(sub)
    c = {"cx": int(xx.mean()) + s[1].start, "cy": int(yy.mean()) + s[0].start, "w": w, "h": h}
    if not (BX[0] <= c["cx"] <= BX[1] and BX[2] <= c["cy"] <= BX[3]):
        continue
    c["touch"] = set()
    for lid in COLOR:
        f = DF[lid]
        d = min(float(f[c["cy"], c["cx"]]),
                float(f[max(0, s[0].start - 3):s[0].stop + 3, max(0, s[1].start - 3):s[1].stop + 3].min()))
        if d <= 22:
            c["touch"].add(lid)
    if c["touch"]:
        circ.append(c)
print(f"有效圆点 {len(circ)}")

name2ocr = {}
for o in OCR:
    t = norm(o["text"])
    if t in ST:
        name2ocr.setdefault(t, []).append(o)
for nm in ST:
    if nm in name2ocr:
        continue
    m = difflib.get_close_matches(nm, [norm(o["text"]) for o in OCR], n=1, cutoff=0.9)
    if m:
        name2ocr[nm] = [o for o in OCR if norm(o["text"]) == m[0]]


def box_dist(cx, cy, o):
    dx = max(o["x"] - cx, 0, cx - (o["x"] + o["w"]))
    dy = max(o["y"] - cy, 0, cy - (o["y"] + o["h"]))
    return (dx * dx + dy * dy) ** 0.5


def anchor_cost(nm, c):
    """锚点代价：优先 OCR 框（到框最近边），无 OCR 用旧坐标 ×0.6"""
    best = None
    for o in name2ocr.get(nm, []):
        d = box_dist(c["cx"], c["cy"], o)
        best = d if best is None else min(best, d)
    if best is not None:
        return min(best, 200)
    s = ST[nm]
    return min(((s["x"] - c["cx"]) ** 2 + (s["y"] - c["cy"]) ** 2) ** 0.5 * 0.6, 200)


final = {}
report = []
for lid, seq in ORDER.items():
    if not seq or lid in FROZEN:
        continue
    seq = [nm for nm in seq if nm in ST and not (set(ST[nm]["lines"]) & FROZEN)]
    if len(seq) < 2:
        continue
    C = [j for j, c in enumerate(circ) if lid in c["touch"]]
    if len(C) < 2:
        report.append(f"{lid}号线：贴线圆点不足({len(C)})，跳过")
        continue
    k, m = len(seq), len(C)
    ac = np.array([[anchor_cost(seq[i], circ[j]) for j in C] for i in range(k)])
    step = np.array([[np.hypot(circ[C[a]]["cx"] - circ[C[b]]["cx"], circ[C[a]]["cy"] - circ[C[b]]["cy"])
                      for b in range(m)] for a in range(m)])
    INF = 1e9
    dp = ac[0].copy()
    prev = np.full((k, m), -1, dtype=int)
    for i in range(1, k):
        nd = np.full(m, INF); pv = np.full(m, -1, dtype=int)
        for b in range(m):
            cand = dp + 0.35 * step[:, b]
            cand[b] = INF          # 同一圆点不能被相邻两站占用
            a0 = int(np.argmin(cand))
            nd[b] = cand[a0] + ac[i, b]
            pv[b] = a0
        dp, prev[i] = nd, pv
    b = int(np.argmin(dp))
    chain = [b]
    for i in range(k - 1, 0, -1):
        b = int(prev[i][b]); chain.append(b)
    chain.reverse()
    for i, j in enumerate(chain):
        final.setdefault(seq[i], {})[lid] = (circ[C[j]]["cx"], circ[C[j]]["cy"])
    report.append(f"{lid}号线：{k} 站 DP 完成（候选圆点 {m}）  总代价 {dp.min():.0f}")

# 合并多线结果（同一站应各线一致）
merged, conflict = {}, []
for nm, per in final.items():
    pts = set(per.values())
    if len(pts) == 1:
        merged[nm] = list(next(iter(pts)))
    else:
        conflict.append((nm, per))
print(f"DP 认领 {len(merged)} 站；多线结果不一致 {len(conflict)} 站：" +
      "、".join(nm for nm, _ in conflict[:15]))

active = [nm for nm in ST if not (set(ST[nm]["lines"]) & FROZEN)]
miss = [nm for nm in active if nm not in merged]
print(f"未认领 {len(miss)} 站：" + "、".join(miss))

json.dump({"merged": merged, "conflict": conflict, "miss": miss},
          open(SRC + "/logs/_assign_dp.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n".join(report[:25]))
print("已写出 logs/_assign_dp.json")
