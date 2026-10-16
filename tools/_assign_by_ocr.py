# -*- coding: utf-8 -*-
"""门2（只读）：用图上自带的站名文字(OCR) 给圆点自动认领站名。

不用用户读表格：OCR 框与圆点一一配对（距离用「圆点到 OCR 矩形最近边」，
因为站名文字是摆在圆点旁边的，用中心距离会偏）。

冻结：坪山云巴 / 有轨电车 / 有轨电车支线 —— 原图中间站没有圆点，保持现状不动。

产物：logs/_assign_by_ocr.json + logs/自动认领结果.md
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
COLOR.update({"4": "#E71615", "11": "#6D2041"})     # 实测色


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def norm(s):
    return "".join(ch for ch in s.strip() if ch not in " 　:：·.、-—")


# ---------- 走廊场 ----------
DF = {}
for lid, c in COLOR.items():
    r, g, b = hex2rgb(c)
    m = (np.abs(img[:, :, 0] - r) + np.abs(img[:, :, 1] - g) + np.abs(img[:, :, 2] - b)) <= 20
    DF[lid] = ndimage.distance_transform_edt(~ndimage.binary_erosion(m, np.ones((3, 3))))

# ---------- 圆点 ----------
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
    c = {"cx": int(xx.mean()) + s[1].start, "cy": int(yy.mean()) + s[0].start, "w": w, "h": h,
         "x0": s[1].start, "y0": s[0].start, "x1": s[1].stop, "y1": s[0].stop}
    if not (BX[0] <= c["cx"] <= BX[1] and BX[2] <= c["cy"] <= BX[3]):
        continue
    c["touch"] = {}
    for lid in COLOR:
        f = DF[lid]
        d = min(float(f[c["cy"], c["cx"]]),
                float(f[max(0, c["y0"] - 3):c["y1"] + 3, max(0, c["x0"] - 3):c["x1"] + 3].min()))
        if d <= 22:
            c["touch"][lid] = round(d, 1)
    if c["touch"]:
        circ.append(c)
print(f"有效圆点 {len(circ)}")

# ---------- OCR 框 ----------
names = list(ST.keys())
name2ocr = {}
for o in OCR:
    t = norm(o["text"])
    if t in ST:
        name2ocr.setdefault(t, []).append(o)
for nm in names:                       # 模糊兜底
    if nm in name2ocr:
        continue
    m = difflib.get_close_matches(nm, [norm(o["text"]) for o in OCR], n=1, cutoff=0.9)
    if m:
        name2ocr[nm] = [o for o in OCR if norm(o["text"]) == m[0]]
print(f"站名有 OCR 框的 {len(name2ocr)} / {len(names)}")


def box_dist(c, o):
    dx = max(o["x"] - c["cx"], 0, c["cx"] - (o["x"] + o["w"]))
    dy = max(o["y"] - c["cy"], 0, c["cy"] - (o["y"] + o["h"]))
    return (dx * dx + dy * dy) ** 0.5


# ---------- 贪心一对一认领 ----------
cand = []
for nm in names:
    if set(ST[nm]["lines"]) & FROZEN:
        continue
    for o in name2ocr.get(nm, []):
        for j, c in enumerate(circ):
            d = box_dist(c, o)
            if d <= 170:
                cand.append((d, nm, j, bool(set(ST[nm]["lines"]) & set(c["touch"]))))
cand.sort(key=lambda t: (not t[3], t[0]))     # 先满足"贴本站所属线"的
used_c, used_s, assign = set(), set(), {}
for d, nm, j, ok in cand:
    if nm in used_s or j in used_c:
        continue
    assign[nm] = {"circle": (circ[j]["cx"], circ[j]["cy"]), "d": round(d, 1),
                  "touch_ok": ok, "size": [circ[j]["w"], circ[j]["h"]],
                  "touch": sorted(circ[j]["touch"])}
    used_s.add(nm); used_c.add(j)

active = [nm for nm in names if not (set(ST[nm]["lines"]) & FROZEN)]
miss = [nm for nm in active if nm not in assign]
print(f"自动认领 {len(assign)} / {len(active)} 站（云巴/电车 {len(names)-len(active)} 站已冻结）")
print(f"未认领 {len(miss)} 站：{'、'.join(miss)}")
bad = [nm for nm in assign if not assign[nm]["touch_ok"]]
print(f"认领了但不贴本站所属线的 {len(bad)} 站：{'、'.join(bad)}")

json.dump(assign, open(SRC + "/logs/_assign_by_ocr.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("已写出 logs/_assign_by_ocr.json")
