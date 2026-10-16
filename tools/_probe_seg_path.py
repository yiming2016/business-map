# -*- coding: utf-8 -*-
"""打印某一站对之间的**最终路径点**（八向化 + 倒圆角之后，用户真正看到的形状）。

用法：
    python tools/_probe_seg_path.py <线号> <站A> <站B>
例：
    python tools/_probe_seg_path.py 5 黄贝岭 湖贝
"""
import json
import math
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtCore import QPointF                                  # noqa: E402
from ui.map_view import build_line_points_ex, line_station_xy       # noqa: E402
from ui.metro_render import (octilinear_waypoints_tagged,           # noqa: E402
                             build_octilinear_path, FILLET_RADIUS)


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    app = QApplication.instance() or QApplication(sys.argv[:1])     # noqa: F841
    lid, A, B = str(sys.argv[1]), sys.argv[2], sys.argv[3]
    st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj
    L = next(x for x in lines if str(x.get("id")) == lid)
    seq = [n for n in (L.get("stations") or []) if n in st]
    print("FILLET_RADIUS =", FILLET_RADIUS)
    for nm in (A, B):
        s = st.get(nm) or {}
        print("\n【%s】 站心 (%s, %s)  lines=%s" % (nm, s.get("x"), s.get("y"), s.get("lines")))
        if s.get("lanes"):
            print("   lanes      =", s["lanes"])
        if s.get("alt_bodies"):
            print("   alt_bodies =", s["alt_bodies"])
        if s.get("pill"):
            print("   pill       =", s["pill"])
        print("   本线落脚点 =", line_station_xy(s, lid))

    pts, ebl, keys = build_line_points_ex(lid, seq, st, want_keys=True)
    iA = iB = None
    for i, nm in enumerate(seq):
        if nm == A:
            iA = i
        elif nm == B:
            iB = i
    if iA is None or iB is None:
        print("站序里找不到这两站")
        return 1
    lo, hi = min(iA, iB), max(iA, iB)
    pa = line_station_xy(st[seq[lo]], lid)
    pb = line_station_xy(st[seq[hi]], lid)
    d = (st[seq[lo]].get("lanes") or {}).get(lid)
    if d:
        pa = (pa[0] + float(d[0]), pa[1] + float(d[1]))
    d = (st[seq[hi]].get("lanes") or {}).get(lid)
    if d:
        pb = (pb[0] + float(d[0]), pb[1] + float(d[1]))
    print("\n段 %s→%s  走廊点 A%s B%s  直线长 %.1f"
          % (seq[lo], seq[hi], pa, pb, math.hypot(pb[0] - pa[0], pb[1] - pa[1])))
    print("（A→B 直线方向 %.1f°）"
          % (math.degrees(math.atan2(pb[1] - pa[1], pb[0] - pa[0])) % 360))

    print("\n—— build_line_points_ex 的原始点列（这一段附近 ±3 点）——")
    ia = ib = None
    for k in range(len(pts)):
        if (abs(pts[k].x() - pa[0]) < 0.51 and abs(pts[k].y() - pa[1]) < 0.51
                and ia is None):
            ia = k
        if (abs(pts[k].x() - pb[0]) < 0.51 and abs(pts[k].y() - pb[1]) < 0.51
                and ia is not None and ib is None):
            ib = k
    if ia is None or ib is None:
        print("点列里定位不到，打印全列")
        ia, ib = 0, len(pts) - 1
    for k in range(max(0, ia - 3), min(len(pts), ib + 4)):
        mark = " <<<" if k == ia or k == ib else ""
        print("  %3d  (%9.1f,%9.1f)  ebl=%-6s key=%s%s"
              % (k, pts[k].x(), pts[k].y(), ebl[k] if k < len(ebl) else "?",
                 keys[k] if k < len(keys) else "?", mark))

    tagged = octilinear_waypoints_tagged(pts, ebl)
    print("\n—— 八向化之后的点数：%d（原 %d）——" % (len(tagged), len(pts)))
    for k in range(max(0, ia - 2), min(len(tagged), ib + 8)):
        p, isst = tagged[k]
        print("  %3d  (%9.1f,%9.1f)  站点=%s" % (k, p.x(), p.y(), isst))

    path = build_octilinear_path(pts, radius=FILLET_RADIUS, elbows=ebl)
    print("\n—— 最终路径（按弧长每 5%% 采一点）——")
    for i in range(21):
        p = path.pointAtPercent(i / 20.0)
        print("   t=%.2f  (%9.1f,%9.1f)" % (i / 20.0, p.x(), p.y()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
