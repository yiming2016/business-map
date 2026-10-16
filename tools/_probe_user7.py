# -*- coding: utf-8 -*-
"""只读诊断：用户点名的 7 处（8 段）为什么还歪。"""
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_closing, distance_transform_edt, label

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import core.data_manager as CDM

CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"
import fix_fit_official as F
import fix_retrace_from_official as FR

ST, DOC, LINES = F.ST, F.DOC, F.LINES
TR = DOC.get("traced") or {}
OO = set(DOC.get("octi_off") or [])

SEGS = [("12", "国展", "国展北"), ("20", "国展", "国展北"),
        ("5", "临海", "宝华"), ("11", "前海湾", "南山"),
        ("2", "水湾", "东角头"), ("2", "东角头", "湾厦"), ("2", "湾厦", "海月"),
        ("2", "登良", "后海"), ("2", "后海", "科苑"),
        ("7", "西丽湖", "西丽"), ("5", "留仙洞", "西丽"), ("5", "西丽", "大学城")]


def rgb_of(lid):
    e = FR.COLORS.get(lid)
    return e["colors"][0][0] if isinstance(e, dict) else e


def blob(lid, A, B, margin=200.0):
    x0 = max(0, int(min(A[0], B[0]) - margin))
    y0 = max(0, int(min(A[1], B[1]) - margin))
    x1 = min(8000, int(max(A[0], B[0]) + margin))
    y1 = min(8000, int(max(A[1], B[1]) + margin))
    c = rgb_of(lid)
    blk = FR.OFF[y0:y1, x0:x1]
    m = np.abs(blk - np.array(c, dtype=np.int16)).sum(axis=2) < F.TOL
    raw = int(m.sum())
    m2 = binary_closing(m, structure=np.ones((9, 9)))
    lab, n = label(m2)
    if n > 1:
        sz = np.bincount(lab.ravel())
        sz[0] = 0
        m2 = (lab == int(sz.argmax()))
    if int(m2.sum()) == 0:
        return None
    D = distance_transform_edt(m2)
    return (m2, D, x0, y0, raw, float(np.median(D[m2])))


print("%-4s %-16s %-5s %-7s %-9s %-9s %-9s %s" % (
    "线", "段(按站序)", "描线", "免八向", "掩膜px", "带宽中位", "段偏移p90", "A*重描"))
print("-" * 105)
for lid, a, b in SEGS:
    seq = [n for n in (next(x for x in LINES if str(x.get("id")) == lid).get("stations") or []) if n in ST]
    if a not in seq or b not in seq:
        print("%-4s %-16s 站不在本线" % (lid, a + "→" + b))
        continue
    ia, ib = seq.index(a), seq.index(b)
    if ia > ib:
        ia, ib, a, b = ib, ia, b, a
    key = "%s|%s|%s" % (lid, a, b)
    A = F.corridor_pt(a, lid)
    B = F.corridor_pt(b, lid)
    poly = F.drawn_polyline(lid, seq)
    seg = F.slice_between(poly, A, B)
    bb = blob(lid, A, B)
    if bb is None:
        print("%-4s %-16s 块内无该线像素" % (lid, a + "→" + b))
        continue
    m, D, x0, y0, raw, med = bb
    st = F.stats(F.offsets(D, x0, y0, F.trim(seg)))

    def dat(p):
        xi, yi = int(round(p[0] - x0)), int(round(p[1] - y0))
        if 0 <= xi < D.shape[1] and 0 <= yi < D.shape[0]:
            return float(D[yi, xi])
        return -1.0

    c = rgb_of(lid)
    try:
        P, why = FR.trace_seg(c, A, B)
        astr = why if P is None else ("%d点" % len(FR.dedup(FR.rdp(P, 5.0))))
    except Exception as ex:
        astr = "ERR %r" % (ex,)
    L = float(sum(np.hypot(seg[k + 1][0] - seg[k][0], seg[k + 1][1] - seg[k][1]) for k in range(len(seg) - 1)))
    print("%-4s %-16s %-5s %-7s %-9d %-9.1f %-9s %s" % (
        lid, a + "→" + b, "有" if key in TR else "无", "是" if key in OO else "否",
        raw, med, ("%.1f" % st[1]) if st else "-", astr))
    print("     端点离带中心 D: A=%.1f B=%.1f（带宽约 %.1f）  渲染段长 %.0f px  段点数 %d" % (
        dat(A), dat(B), med * 4, L, len(seg)))
