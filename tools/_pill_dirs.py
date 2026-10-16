# -*- coding: utf-8 -*-
"""只读：把每个换乘站「原图胶囊的实际方向」与「各条线在该站附近的走向」逐条对照。
产物 logs/_pill_dirs.txt
"""
import json
import math
from collections import Counter

import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
DATA = json.load(open(SRC + "/data/stations.json", encoding="utf-8"))
ST = DATA["stations"]
LINES = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))


def xy(name):
    s = ST.get(name)
    return (float(s["x"]), float(s["y"])) if s else None


def ang_of(a, c):
    """由 a->c 的方向决定（a、c 是同一线上该站的前后邻站）。"""
    pa, pc = xy(a), xy(c)
    if not pa or not pc:
        return None
    dx, dy = pc[0] - pa[0], pc[1] - pa[1]
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return None
    return math.degrees(math.atan2(dy, dx)) % 180


# ---- 每条线的站序 ----
line_orders = {}
for L in LINES["lines"]:
    line_orders[str(L["id"])] = [n for n in (L.get("stations") or [])]

# ---- 每站：各线走向 ----
station_dir = {}
for lid, seq in line_orders.items():
    for i, nm in enumerate(seq):
        if nm not in ST:
            continue
        prev = seq[i - 1] if i > 0 else None
        nxt = seq[i + 1] if i + 1 < len(seq) else None
        a = prev or nxt
        c = nxt or prev
        ang = ang_of(a, c) if (a and c) else None
        if ang is None:
            continue
        station_dir.setdefault(nm, {})[lid] = ang

# ---- 原图胶囊实际方向 ----
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
white = (np.abs(img[:, :, 0] - 254) + np.abs(img[:, :, 1] - 254) + np.abs(img[:, :, 2] - 254)) <= 10
white = ndimage.binary_erosion(white, np.ones((3, 3)))
white[6100:, 5700:] = False
lab, n = ndimage.label(white, np.ones((3, 3)))

pills = []          # (cx, cy, w, h, deg, elong)
for i, sl in enumerate(ndimage.find_objects(lab), 1):
    if sl is None:
        continue
    m = (lab[sl] == i)
    area = int(m.sum())
    h = sl[0].stop - sl[0].start
    w = sl[1].stop - sl[1].start
    if area < 300 or max(w, h) > 140 or min(w, h) < 14:
        continue
    if area / (w * h) < 0.72:
        continue
    ys, xs = np.where(m)
    cov = np.cov(np.stack([xs, ys]))
    ev, evec = np.linalg.eigh(cov)
    vx, vy = evec[0, -1], evec[1, -1]
    deg = math.degrees(math.atan2(vy, vx)) % 180
    elong = math.sqrt(ev[-1]) / max(math.sqrt(ev[0]), 1e-6)
    pills.append((xs.mean() + sl[1].start, ys.mean() + sl[0].start, w, h, deg, elong))

# ---- 每个胶囊找最近站 ----
def near(cx, cy, lim=120):
    out = []
    for nm, s in ST.items():
        d = math.hypot(float(s["x"]) - cx, float(s["y"]) - cy)
        if d <= lim:
            out.append((d, nm))
    out.sort()
    return out


rows = []
for cx, cy, w, h, deg, elong in pills:
    if elong < 1.45:
        continue
    ns = near(cx, cy)
    if not ns:
        continue
    nm = ns[0][1]
    rows.append((nm, cx, cy, w, h, deg, elong, ns[0][0]))

rows.sort(key=lambda r: r[0])


def norm(a):
    return a % 180


def diff(a, b):
    d = abs(norm(a) - norm(b)) % 180
    return min(d, 180 - d)


def lab_of(deg):
    d = norm(deg)
    if d <= 22.5 or d >= 157.5:
        return "横"
    if 67.5 <= d <= 112.5:
        return "竖"
    return "斜"


out = ["# 换乘站：原图胶囊方向 vs 各线路走向", "",
       "角度定义：0°=水平(横)，45°=右下斜，90°=竖直，135°=左下斜。", ""]
out.append("| 站名 | 原图胶囊 | 方向 | 该站线路:走向 | 与胶囊同向的线 | 与胶囊垂直的线 |")
out.append("|---|---|---|---|---|---|")
mismatch = []
for nm, cx, cy, w, h, deg, elong, d in rows:
    dirs = station_dir.get(nm, {})
    if not dirs:
        continue
    parts = "; ".join("%s:%s %.0f°" % (lid, lab_of(a), a) for lid, a in sorted(dirs.items()))
    same = [lid for lid, a in dirs.items() if diff(a, deg) <= 25]
    perp = [lid for lid, a in dirs.items() if abs(diff(a, deg) - 90) <= 25]
    diag = [lid for lid, a in dirs.items() if 25 < diff(a, deg) < 65]
    out.append("| %s | %dx%d | **%s** %.0f° | %s | %s | %s |"
               % (nm, w, h, lab_of(deg), deg, parts, "/".join(sorted(same)) or "-",
                  "/".join(sorted(perp)) or "-"))
    if not same:
        mismatch.append((nm, lab_of(deg), deg, parts))

out.append("")
out.append("## 胶囊方向与所有线都不一致（需人工看）的站：%d 个" % len(mismatch))
out.append("")
for nm, k, deg, parts in mismatch:
    out.append("- **%s**（胶囊%s %.0f°）：%s" % (nm, k, deg, parts))

open(SRC + "/logs/_pill_dirs.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out[:6]))
print("...")
print("mismatch", len(mismatch))
