# -*- coding: utf-8 -*-
"""打印某一段真正画出来的折线：每个顶点的坐标 / 边长 / 转角。"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))
import core.data_manager as CDM                      # noqa: E402

CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"

from ui.map_view import build_line_points_ex          # noqa: E402
from ui import metro_render as MR                     # noqa: E402

dm = CDM.get_data_manager()
st = dm.all_stations()


def ang(u, v):
    lu = math.hypot(*u)
    lv = math.hypot(*v)
    if lu < 1e-9 or lv < 1e-9:
        return 0.0
    c = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (lu * lv)))
    return math.degrees(math.acos(c))


def show(lid, a, b):
    pts, ebl, keys = build_line_points_ex(lid, [a, b], st, want_keys=True)
    w = MR.octilinear_waypoints_tagged(pts, ebl)
    P = [(p.x(), p.y()) for p, _s in w]
    print("=" * 78)
    print("%s|%s|%s   pts=%d -> waypoints=%d" % (lid, a, b, len(pts), len(P)))
    print("  [build_line_points_ex]")
    for i, p in enumerate(pts):
        print("    p%-2d (%8.1f,%8.1f)  ebl=%-9s key=%s"
              % (i, p.x(), p.y(), ebl[i] if i < len(ebl) else "?",
                 keys[i] if i < len(keys) else "?"))
    print("  [最终折线]")
    for i, (x, y) in enumerate(P):
        seg = ""
        if 0 < i < len(P) - 1:
            L = math.hypot(x - P[i - 1][0], y - P[i - 1][1])
            t = ang((x - P[i - 1][0], y - P[i - 1][1]),
                    (P[i + 1][0] - x, P[i + 1][1] - y))
            seg = "  边长 %.1f  转角 %.1f°" % (L, t)
        else:
            if i:
                seg = "  边长 %.1f" % math.hypot(x - P[i - 1][0], y - P[i - 1][1])
        print("    w%-2d (%8.1f,%8.1f)%s" % (i, x, y, seg))


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 3:
        show(args[0], args[1], args[2])
    else:
        for k in ["11|前海湾|南山", "7|车公庙|上沙"]:
            lid, a, b = k.split("|")
            show(lid, a, b)
