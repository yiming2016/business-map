# -*- coding: utf-8 -*-
"""只读：从原图量出每个换乘站的「胶囊几何」与「各线路走廊偏移」。

原理（已由 _probe_lanes.py 实测验证）：
  · 胶囊 = 白色圆角矩形 + 近黑描边(约5px) + 白色内部；
    内部被描边完全围住 ⇒ 从站中心在白色掩膜上泛洪，得到的即胶囊内部。
  · 各条线在换乘站附近"各占一条走廊"，间距约 50px；
    对某条线的颜色掩膜做总体最小二乘拟合，把站中心投影上去 ⇒ 偏移向量。

产物 logs/_transfer_layout.txt（人读）+ data/transfer_layout.json（机读）
"""
import json
import math
from collections import Counter

import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int32)
H, W = img.shape[:2]
DATA = json.load(open(SRC + "/data/stations.json", encoding="utf-8"))
ST = DATA["stations"]
LINES = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))["lines"]

LINE_COLOR = {}
for L in LINES:
    c = L["color"].lstrip("#")
    LINE_COLOR[str(L["id"])] = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
# 颜色重复的线路（分不清是哪条）⇒ 这些线不做走廊测量
COLOR_OWNERS = {}
for lid, col in LINE_COLOR.items():
    COLOR_OWNERS.setdefault(col, []).append(lid)
AMBIG = {col for col, owners in COLOR_OWNERS.items() if len(owners) > 1}

WHITE = np.min(img, axis=2) >= 244
DARK = np.max(img, axis=2) < 115


def pill_of(cx, cy, half=130):
    """从站中心泛洪得到胶囊内部，返回 (ang_deg, 长半轴, 短半轴, 面积)。"""
    x0, y0 = max(0, cx - half), max(0, cy - half)
    x1, y1 = min(W, cx + half), min(H, cy + half)
    sub = WHITE[y0:y1, x0:x1]
    lx, ly = cx - x0, cy - y0
    if not (0 <= ly < sub.shape[0] and 0 <= lx < sub.shape[1]) or not sub[ly, lx]:
        # 中心不是白的（可能站名压到/描边）→ 就近找白点
        ys, xs = np.where(sub)
        if len(xs) == 0:
            return None
        k = np.argmin((xs - lx) ** 2 + (ys - ly) ** 2)
        lx, ly = xs[k], ys[k]
    lab, _ = ndimage.label(sub, np.ones((3, 3)))
    lid = lab[ly, lx]
    if lid == 0:
        return None
    m = lab == lid
    area = int(m.sum())
    ys, xs = np.where(m)
    if area < 120 or area > 40000:
        return None
    bw = xs.max() - xs.min() + 1
    bh = ys.max() - ys.min() + 1
    if bw > 210 or bh > 210:
        return None
    cov = np.cov(np.stack([xs.astype(float), ys.astype(float)]))
    ev, evec = np.linalg.eigh(cov)
    v = evec[:, -1]
    ang = math.degrees(math.atan2(v[1], v[0])) % 180
    u = np.array([math.cos(math.radians(ang)), math.sin(math.radians(ang))])
    w = np.array([-u[1], u[0]])
    long_r = float(np.abs((xs - xs.mean()) * u[0] + (ys - ys.mean()) * u[1]).max())
    short_r = float(np.abs((xs - xs.mean()) * w[0] + (ys - ys.mean()) * w[1]).max())
    return ang, long_r, short_r, area


def lane_of(cx, cy, lid, present=(), rmin=16, rmax=120):
    """某条线在该站附近的走廊：返回偏移向量 (dx,dy) 与走廊方向角。

    ★ 2号线/8号线同色(#BA5700)、有轨电车/坪山云巴同色(#B6B6B7)——
      只要能确认"同色的另一条线不在本站"，就仍然能唯一归属。
    """
    col = LINE_COLOR.get(lid)
    if col is None:
        return None
    if col in AMBIG and len([o for o in COLOR_OWNERS[col] if o in present]) != 1:
        return None
    x0, y0 = max(0, cx - rmax), max(0, cy - rmax)
    x1, y1 = min(W, cx + rmax), min(H, cy + rmax)
    sub = img[y0:y1, x0:x1]
    d = np.abs(sub - np.array(col, dtype=np.int32)).sum(axis=2)
    m = d <= 60
    ys, xs = np.where(m)
    if len(xs) < 40:
        return None
    X = xs.astype(float) + x0
    Y = ys.astype(float) + y0
    rr = np.hypot(X - cx, Y - cy)
    keep = (rr >= rmin) & (rr <= rmax)
    if keep.sum() < 40:
        return None
    X, Y = X[keep], Y[keep]
    mx, my = X.mean(), Y.mean()
    cov = np.cov(np.stack([X - mx, Y - my]))
    ev, evec = np.linalg.eigh(cov)
    el = math.sqrt(max(ev[-1], 1e-9)) / max(math.sqrt(max(ev[0], 1e-9)), 1e-6)
    v = evec[:, -1]
    # 站中心在拟合线上的垂足
    t = (cx - mx) * v[0] + (cy - my) * v[1]
    fx, fy = mx + t * v[0], my + t * v[1]
    ang = math.degrees(math.atan2(v[1], v[0])) % 180
    return (fx - cx, fy - cy), ang, el, int(keep.sum())


st_names = sorted(ST.keys())
out = {}
rep = ["# 换乘站：原图胶囊几何 + 各线路走廊偏移", "",
       "偏移 = 该线走廊中心相对站中心的向量（原图像素）。", ""]
npill = nlane = 0
for nm in st_names:
    s = ST[nm]
    lines = [str(x) for x in (s.get("lines") or [])]
    if len(lines) < 2:
        continue
    cx, cy = int(round(float(s["x"]))), int(round(float(s["y"])))
    if not (0 <= cx < W and 0 <= cy < H):
        continue
    p = pill_of(cx, cy)
    rec = {}
    if p:
        ang, lr, sr, area = p
        rec["pill"] = {"ang": round(ang, 1), "rl": round(lr, 1), "rs": round(sr, 1)}
        npill += 1
    lanes = {}
    for lid in lines:
        r = lane_of(cx, cy, lid, present=set(lines))
        if r is None:
            continue
        (dx, dy), ang, el, n = r
        if el < 2.2:            # 拟合不出一根线（点太散）⇒ 不信
            continue
        # [dx, dy, 走廊方向角, 拟合拉长度] —— 后两项供渲染层"顺走廊穿过去"用；
        # 拟合质量 el 越高方向越可信（细长的一条线），低于 3.0 时渲染层退回用站序方向。
        lanes[lid] = [round(dx, 1), round(dy, 1), round(ang, 1), round(el, 2)]
    if lanes:
        rec["lanes"] = lanes
        nlane += len(lanes)
    if rec:
        out[nm] = rec
    rep.append("- **%s** (%d,%d) 线=%s" % (nm, cx, cy, "/".join(lines)))
    if "pill" in rec:
        p2 = rec["pill"]
        rep.append("  - 胶囊: 角 %.0f°  长半轴 %.1f (全长 %.0f)  短半轴 %.1f (全宽 %.0f)"
                   % (p2["ang"], p2["rl"], p2["rl"] * 2 + 1, p2["rs"], p2["rs"] * 2 + 1))
    else:
        rep.append("  - 胶囊: **没找到**")
    if "lanes" in rec:
        for lid, v in sorted(rec["lanes"].items()):
            dx, dy, lang, lel = v
            rep.append("  - 线%-4s 走廊偏移 (%+.0f,%+.0f) 距离 %.0f  走向 %.0f°  拟合 %.1f"
                       % (lid, dx, dy, math.hypot(dx, dy), lang, lel))

json.dump(out, open(SRC + "/data/transfer_layout.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
open(SRC + "/logs/_transfer_layout.txt", "w", encoding="utf-8").write("\n".join(rep))
print("站数", len(out), "胶囊", npill, "走廊", nlane)
