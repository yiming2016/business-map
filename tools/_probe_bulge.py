# -*- coding: utf-8 -*-
"""只读诊断：哪一段线路被"鼓"出了包？

用户原话：「在两站都是换乘站的情况下，线路的轨道会出现严重变形」。

★ 必须用**整条线**跑 `build_line_points_ex`，不能用"4 站窗口"——
  窗口会把端点站也塞到中间，于是插了实际渲染中根本不存在的走廊替身点，
  量出来的东西和用户看到的不一样（第一版探针就栽在这）。
  整线 pts 里用**坐标精确匹配**定位每站的走廊点，再量 pts[iA..iB]（真正画
  出来的中间点）相对 "A→B 直线" 的**最大垂距 / 段长**。
  正常八向折线 ≤0.30（斜段最多让线绕 41%），鼓包会明显超过。

用法：
    python tools/_probe_bulge.py [线号]
"""
import json
import math
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication          # noqa: E402
from ui.map_view import build_line_points_ex, line_station_xy   # noqa: E402


def off_point(st, lid):
    """某站在某线上的走廊点（= build_line_points_ex 里 ox,oy 的算法）"""
    x, y = line_station_xy(st, lid)
    d = (st.get("lanes") or {}).get(str(lid))
    if d:
        try:
            x = x + float(d[0])
            y = y + float(d[1])
        except (TypeError, ValueError, IndexError):
            pass
    return (float(x), float(y))


def idx_of(pts, target):
    out = []
    for k in range(len(pts)):
        if (abs(float(pts[k].x()) - target[0]) < 0.51
                and abs(float(pts[k].y()) - target[1]) < 0.51):
            out.append(k)
    return out


def seg_stats(pts, i0, i1):
    ax, ay = float(pts[i0].x()), float(pts[i0].y())
    bx, by = float(pts[i1].x()), float(pts[i1].y())
    dx, dy = bx - ax, by - ay
    L = math.hypot(dx, dy)
    if L < 1e-6:
        return 0.0, 0.0, 0.0
    ux, uy = dx / L, dy / L
    worst, wt = 0.0, 0.0
    prev = 0.0
    maxstep = 0.0
    for k in range(i0, i1 + 1):
        px, py = float(pts[k].x()), float(pts[k].y())
        t = (px - ax) * ux + (py - ay) * uy
        d = abs((px - ax) * -uy + (py - ay) * ux)
        if d > worst:
            worst, wt = d, t / L
        if k > i0:
            maxstep = max(maxstep, abs(t - prev))
        prev = t
    return worst, L, wt, maxstep


def main():
    app = QApplication.instance() or QApplication(sys.argv[:1])   # noqa: F841
    st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj

    want = sys.argv[1] if len(sys.argv) > 1 else None
    rows = []
    for L in lines:
        lid = str(L.get("id"))
        if want and lid != want:
            continue
        seq = [n for n in (L.get("stations") or []) if n in st]
        if len(seq) < 2:
            continue
        pts, ebl, keys = build_line_points_ex(lid, seq, st, want_keys=True)
        for i in range(1, len(seq)):
            a, b = seq[i - 1], seq[i]
            pa, pb = off_point(st[a], lid), off_point(st[b], lid)
            best = None
            for ia in idx_of(pts, pa):
                for ib in idx_of(pts, pb):
                    if ib > ia and (best is None or ib - ia < best[1] - best[0]):
                        best = (ia, ib)
            if best is None or best[1] - best[0] < 1:
                continue
            ia, ib = best
            dev, lng, wt, mstep = seg_stats(pts, ia, ib)
            if lng < 1e-6:
                continue
            ta = len((st.get(a) or {}).get("lines") or []) > 1
            tb = len((st.get(b) or {}).get("lines") or []) > 1
            tags = set()
            for k in range(ia + 1, ib + 1):
                if k < len(ebl) and ebl[k]:
                    tags.add(ebl[k])
            if abs(wt) > 1.001:
                tags.add("★overshoot(t=%.2f)" % wt)
            rows.append(dict(lid=lid, a=a, b=b, dev=dev, lng=lng, r=dev / lng,
                             wt=wt, both=(ta and tb), ta=ta, tb=tb,
                             tags=",".join(sorted(tags)) or "-",
                             n=ib - ia - 1, mstep=mstep,
                             edge=(i == 1 or i == len(seq) - 1)))

    rows.sort(key=lambda r: -(r["r"] + (0.4 if abs(r["wt"]) > 1.001 else 0.0)))
    print("段总数 %d" % len(rows))
    print("\n最鼓的前 32 段（dev=最大垂距，r=垂距/段长，t=鼓包位置，edge=挨着线端点）：")
    print("%-5s %-12s→%-12s %7s %7s %5s %5s %-8s %s"
          % ("线", "上站", "下站", "dev", "段长", "r", "t", "两站换乘", "标记"))
    for r in rows[:32]:
        print("%-5s %-12s→%-12s %7.1f %7.1f %5.2f %5.2f %-8s %s"
              % (r["lid"], r["a"], r["b"], r["dev"], r["lng"], r["r"],
                 r["wt"],
                 "两站都是" if r["both"] else ("仅前" if r["ta"] else
                                               ("仅后" if r["tb"] else "-")),
                 r["tags"] + ("  «端点" if r["edge"] else "")))
    both = [r for r in rows if r["both"]]
    osh = [r for r in rows if abs(r["wt"]) > 1.001]
    print("\n合计：最大垂距>段长30%% 的段 %d 处；鼓包跑到线段外(t>1) %d 处"
          % (sum(1 for r in rows if r["r"] > 0.30), len(osh)))
    if both:
        print("两站都是换乘站的段 %d 个，平均 r=%.3f，最大 r=%.2f"
              % (len(both), sum(r["r"] for r in both) / len(both),
                 max(r["r"] for r in both)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
