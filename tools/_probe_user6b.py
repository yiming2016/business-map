# -*- coding: utf-8 -*-
"""只读探针 2：按**真实全线站序**切出用户点名的区间，看渲染形状 + 离官方同色像素多远。"""
import sys
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))
import core.data_manager as CDM
CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"
from ui.map_view import build_line_points_ex, line_station_xy

OFF = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)
COL = json.loads((ROOT / "_tmp_official_colors.json").read_text(encoding="utf-8"))
TREES = {}


def tree(lid):
    if lid not in TREES:
        e = COL.get(str(lid))
        c = e["colors"][0][0] if isinstance(e, dict) else e
        m = (np.abs(OFF - np.array(c)).sum(axis=2) < 48)
        ys, xs = np.nonzero(m)
        TREES[lid] = cKDTree(np.column_stack([xs, ys]).astype(float))
    return TREES[lid]


def resample(P, step=10.0):
    out = []
    for i in range(len(P) - 1):
        (x0, y0), (x1, y1) = P[i], P[i + 1]
        L = float(np.hypot(x1 - x0, y1 - y0))
        n = max(1, int(np.ceil(L / step)))
        for k in range(n):
            t = k / n
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    out.append(P[-1])
    return np.asarray(out)


def dev(lid, P):
    if len(P) < 2:
        return 0.0
    d, _ = tree(lid).query(resample(P))
    return float(np.percentile(d, 90))


dm = CDM.get_data_manager()
st = dm.all_stations()
doc = dm.lines_doc
TR = doc.get("traced") or {}
OO = set(doc.get("octi_off") or {})
lines = {str(L.get("id")): L for L in (doc.get("lines") or [])}

WANT = [("12", "福海西", "国展北"), ("12", "国展北", None),
        ("11", "桥头", "福永"), ("11", "宝安", "前海湾"), ("11", "后海", "红树湾南"),
        ("5", "前海湾", "临海")]

for lid, a, b in WANT:
    L = lines[lid]
    seq = [n for n in (L.get("stations") or []) if n in st]
    pts, ebl, keys = build_line_points_ex(lid, seq, st, want_keys=True)
    if b is None:
        i = seq.index(a)
        b = seq[i + 1] if i + 1 < len(seq) else None
        if b is None:
            continue
    i0, i1 = seq.index(a), seq.index(b)
    if i0 > i1:
        i0, i1 = i1, i0
    # 用站点落脚点下标在 pts 上定位（描线时 pts 会多出中间点）
    def land(nm):
        x, y = line_station_xy(st[nm], lid)
        d = (st[nm].get("lanes") or {}).get(lid)
        if d:
            try:
                x, y = x + float(d[0]), y + float(d[1])
            except Exception:
                pass
        return (float(x), float(y))
    A, B = land(seq[i0]), land(seq[i1])
    idxs = [k for k, p in enumerate(pts)
            if (abs(p.x() - A[0]) < 0.6 and abs(p.y() - A[1]) < 0.6)
            or (abs(p.x() - B[0]) < 0.6 and abs(p.y() - B[1]) < 0.6)]
    lo, hi = (min(idxs), max(idxs)) if len(idxs) >= 2 else (0, len(pts) - 1)
    seg = [(round(pts[k].x(), 1), round(pts[k].y(), 1)) for k in range(lo, hi + 1)]
    key = "%s|%s|%s" % (lid, seq[i0], seq[i1])
    trv = TR.get(key)
    print("=" * 74)
    print("[%s号线] %s -> %s   段键 %s" % (lid, seq[i0], seq[i1], key))
    print("   描线=%s  octi_off=%s" % (("%d点 %s" % (len(trv), trv)) if trv else "无",
                                        "是" if key in OO else "否"))
    print("   渲染 %d 点: %s" % (len(seg), seg))
    if len(seg) >= 2:
        print("   离官方同色像素 p90 = %.1f px   (线宽约 22px)" % dev(lid, seg))
    sx, sy = seg[0]
    ex, ey = seg[-1]
    print("   两端点: (%.1f,%.1f) -> (%.1f,%.1f)   直线长 %.1f" % (sx, sy, ex, ey, np.hypot(ex - sx, ey - sy)))
