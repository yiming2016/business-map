# -*- coding: utf-8 -*-
"""只读诊断：用户点名的 6 段，**实拍叠图**（官方原图 + 软件真正画出来的线）。

两张量尺一起用，避免"p90 看着小其实局部大偏"：
  · 数值：我的折线每 5px 采样，量到**官方同色像素**的距离，报 p50/p90/p99/max + 最大偏差点。
  · 看图：每段两栏 —— 左=官方原图(全彩)+我的线(品红细线)；右=官方同色掩膜(白)+我的线(红细线)。
    线宽 22px，若我的细线不在官方带子正中间 ⇒ 就是"没贴合"。

用法：python tools/_diag_fit_user6.py
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))
import core.data_manager as CDM
CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"
from ui.map_view import build_line_points_ex, line_station_xy
from ui import metro_render as MR

OFF = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)
COL = json.loads((ROOT / "_tmp_official_colors.json").read_text(encoding="utf-8"))
TOL = 48

dm = CDM.get_data_manager()
st = dm.all_stations()
doc = dm.lines_doc
lines = {str(L.get("id")): L for L in (doc.get("lines") or [])}

SEGS = [("12", "福海西", "国展北"), ("12", "国展北", "海上田园南"),
        ("11", "桥头", "福永"), ("11", "宝安", "前海湾"),
        ("11", "后海", "红树湾南"), ("5", "前海湾", "临海")]


def mask_of(lid):
    e = COL.get(str(lid))
    c = e["colors"][0][0] if isinstance(e, dict) else e
    return c, (np.abs(OFF - np.array(c)).sum(axis=2) < TOL)


def land(nm, lid):
    s = st[nm]
    x, y = line_station_xy(s, lid)
    d = (s.get("lanes") or {}).get(lid)
    if d:
        try:
            x, y = float(x) + float(d[0]), float(y) + float(d[1])
        except Exception:
            pass
    return (float(x), float(y))


def drawn_polyline(lid):
    L = lines[lid]
    seq = [n for n in (L.get("stations") or []) if n in st]
    pts, ebl = build_line_points_ex(lid, seq, st)
    w = MR.octilinear_waypoints_tagged(pts, ebl)
    return [(float(p.x()), float(p.y())) for p, _ in w]


def resample(P, step=5.0):
    out = []
    for i in range(len(P) - 1):
        (x0, y0), (x1, y1) = P[i], P[i + 1]
        L = float(np.hypot(x1 - x0, y1 - y0))
        n = max(1, int(np.ceil(L / step)))
        for k in range(n):
            t = k / n
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    out.append(P[-1])
    return np.asarray(out, dtype=float)


PANEL = (460, 300)
ROWS = []
report = []

for lid, a, b in SEGS:
    poly = drawn_polyline(lid)
    A, B = land(a, lid), land(b, lid)
    # 在**整线**画出来的折线上，按最近顶点切出这一段（和渲染一致）
    ia = int(np.argmin([np.hypot(x - A[0], y - A[1]) for x, y in poly]))
    ib = int(np.argmin([np.hypot(x - B[0], y - B[1]) for x, y in poly]))
    if ia > ib:
        ia, ib = ib, ia
    seg = poly[ia:ib + 1]
    if len(seg) < 2:
        seg = [A, B]

    c, M = mask_of(lid)
    ys, xs = np.nonzero(M)
    MP = np.column_stack([xs, ys]).astype(float)

    S = resample(seg, 5.0)
    # 到最近掩膜像素的距离（分块，避免爆内存）
    dist = np.empty(len(S))
    for k0 in range(0, len(S), 400):
        chunk = S[k0:k0 + 400]
        d2 = ((chunk[:, None, :] - MP[None, :, :]) ** 2).sum(axis=2)
        dist[k0:k0 + 400] = np.sqrt(d2.min(axis=1))
    p50, p90, p99 = (float(np.percentile(dist, q)) for q in (50, 90, 99))
    dmax = float(dist.max())
    kmax = int(np.argmax(dist))
    mx, my = S[kmax]

    report.append(dict(lid=lid, a=a, b=b, npix=int(M.sum()), n_draw=len(seg),
                       p50=p50, p90=p90, p99=p99, dmax=dmax,
                       mx=float(mx), my=float(my),
                       sa=(round(A[0], 1), round(A[1], 1)),
                       sb=(round(B[0], 1), round(B[1], 1))))
    ROWS.append((lid, a, b, seg, A, B, c, M))

print("%-6s %-26s %-8s %6s %6s %6s %6s   %s" %
      ("线", "段", "掩膜px", "p50", "p90", "p99", "max", "最大偏差点"))
for r in report:
    print("%-6s %-26s %8d %6.1f %6.1f %6.1f %6.1f   (%7.1f,%7.1f)" %
          (r["lid"], "%s->%s" % (r["a"], r["b"]), r["npix"],
           r["p50"], r["p90"], r["p99"], r["dmax"], r["mx"], r["my"]))

# ---------------- 出图 ----------------
try:
    from PIL import ImageFont
    F = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 17)
except Exception:
    F = ImageFont.load_default()

W = PANEL[0] * 2 + 12
H = PANEL[1] * len(ROWS) + 6 * (len(ROWS) - 1)
canvas = Image.new("RGB", (W, H), (245, 245, 248))

for ri, (lid, a, b, seg, A, B, c, M) in enumerate(ROWS):
    xs = [p[0] for p in seg] + [A[0], B[0]]
    ys = [p[1] for p in seg] + [A[1], B[1]]
    x0, x1 = min(xs) - 90, max(xs) + 90
    y0, y1 = min(ys) - 90, max(ys) + 90
    sw, sh = x1 - x0, y1 - y0
    s = min(PANEL[0] / sw, PANEL[1] / sh)
    oy = ri * (PANEL[1] + 6)

    # 左：官方原图（全彩）
    crop = Image.fromarray(OFF[max(0, int(y0)):int(y1), max(0, int(x0)):int(x1)].astype(np.uint8))
    crop = crop.resize((max(1, int(sw * s)), max(1, int(sh * s))), Image.NEAREST)
    canvas.paste(crop, (0, oy))
    dr = ImageDraw.Draw(canvas)
    P = [((x - x0) * s, (y - y0) * s + oy) for x, y in seg]
    dr.line(P, fill=(255, 0, 255), width=2, joint="curve")

    # 右：官方同色掩膜（白）+ 我的线（红）
    ox = PANEL[0] + 12
    sub = M[max(0, int(y0)):int(y1), max(0, int(x0)):int(x1)]
    mm = Image.fromarray((sub * 255).astype(np.uint8)).convert("RGB")
    px = mm.load()
    wpx, hpx = mm.size
    for yy in range(hpx):
        for xx in range(wpx):
            if px[xx, yy][0] > 0:
                px[xx, yy] = (0, 170, 0)
            else:
                px[xx, yy] = (25, 25, 30)
    mm = mm.resize((max(1, int(sw * s)), max(1, int(sh * s))), Image.NEAREST)
    canvas.paste(mm, (ox, oy))
    dr = ImageDraw.Draw(canvas)
    P2 = [((x - x0) * s + ox, (y - y0) * s + oy) for x, y in seg]
    dr.line(P2, fill=(255, 60, 60), width=2, joint="curve")
    for x, y in P2:
        dr.ellipse([x - 2.5, y - 2.5, x + 2.5, y + 2.5], fill=(255, 220, 0))

    lab = "%s号线  %s -> %s   (p90=%.1f max=%.1f)" % (lid, a, b, report[ri]["p90"], report[ri]["dmax"])
    dr.rectangle([0, oy, W, oy + 22], fill=(20, 20, 24))
    dr.text((6, oy + 2), lab, fill=(255, 255, 255), font=F)

out = ROOT / "贴合检查_用户点名的6段.png"
canvas.save(out)
print("\n已出图:", out)
