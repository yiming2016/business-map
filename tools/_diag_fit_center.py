# -*- coding: utf-8 -*-
"""只读诊断 2：量"我的线离官方带子**中心线**偏多少"。

之前的量尺（到最近同色像素的距离）有漏洞：带宽 22px，只要还在带子里距离就是 0
⇒ "p50=0.5px"只说明"在带子里"，不说明"居中"。偏 10px 在 4 倍缩放下肉眼可见。

正尺：对官方掩膜做距离变换 D（带内每点到带边缘的距离）。带子中心线的 D ≈ 半宽 hw。
我的线采样点的 D 值 ⇒ 偏中心线的量 = hw - D。D 越小 = 越贴边。

用法：python tools/_diag_fit_center.py
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree

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

dm = CDM.get_data_manager()
st = dm.all_stations()
doc = dm.lines_doc
lines = {str(L.get("id")): L for L in (doc.get("lines") or [])}

SEGS = [("12", "福海西", "国展北"), ("12", "国展北", "海上田园南"),
        ("11", "桥头", "福永"), ("11", "宝安", "前海湾"),
        ("11", "后海", "红树湾南"), ("5", "前海湾", "临海")]


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


def resample(P, step=4.0):
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


print("%-6s %-24s %5s %6s %6s %6s %6s   %s" %
      ("线", "段", "带宽", "偏中p50", "偏中p90", "偏中max", "出带%", "最贴边的点"))
for lid, a, b in SEGS:
    e = COL.get(lid)
    c = e["colors"][0][0] if isinstance(e, dict) else e
    M = (np.abs(OFF - np.array(c)).sum(axis=2) < 48)
    D = distance_transform_edt(M)
    hw = float(np.median(D[M]))                     # 官方带宽的一半

    poly = drawn_polyline(lid)
    A, B = land(a, lid), land(b, lid)
    ia = int(np.argmin([np.hypot(x - A[0], y - A[1]) for x, y in poly]))
    ib = int(np.argmin([np.hypot(x - B[0], y - B[1]) for x, y in poly]))
    if ia > ib:
        ia, ib = ib, ia
    seg = poly[ia:ib + 1]
    if len(seg) < 2:
        seg = [A, B]

    S = resample(seg, 4.0)
    # 掐掉两端各 30px（站点圆点/药丸会盖住官方线，属于测量死角）
    keep = np.ones(len(S), dtype=bool)
    total_len = float(np.hypot(*(S[-1] - S[0]))) if len(S) > 1 else 0
    acc = 0.0
    for k in range(1, len(S)):
        acc += float(np.hypot(*(S[k] - S[k - 1])))
        if acc < 30 or total_len - acc < 30:
            keep[k] = False
    S = S[keep]
    if len(S) < 4:
        print("%-6s %-24s 太短" % (lid, "%s->%s" % (a, b)))
        continue

    xi = np.clip(np.round(S[:, 0]).astype(int), 0, OFF.shape[1] - 1)
    yi = np.clip(np.round(S[:, 1]).astype(int), 0, OFF.shape[0] - 1)
    d_in = D[yi, xi]
    off_center = hw - d_in          # >0 = 偏向带边（0 = 正中心）
    out_band = float((d_in <= 0).mean()) * 100
    p50, p90 = (float(np.percentile(np.abs(off_center), q)) for q in (50, 90))
    kmax = int(np.argmax(np.abs(off_center)))
    print("%-6s %-24s %5.1f %6.1f %6.1f %6.1f %5.0f%%   (%7.1f,%7.1f) D=%.1f" %
          (lid, "%s->%s" % (a, b), hw * 2, p50, p90,
           float(np.abs(off_center).max()), out_band,
           S[kmax][0], S[kmax][1], d_in[kmax]))
