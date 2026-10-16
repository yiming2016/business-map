# -*- coding: utf-8 -*-
"""量化「线路平不顺」：渲染点列里有多少**小转角**（视觉上的波浪/凹凸）。

★ 为什么看"小转角"而不是"离官方线多远"：官方线宽 30px，中心线在带子里左右
  摇摆 ±10px 也还是"贴着官方线"（离最近同色像素 ≈ 0）—— 偏差检查根本抓不到，
  但画出来就是波浪。波浪的本质 = 一串**又短又小的转角**。

指标：
  转角 <10° / 10~25° / 25~45° / ≥45°
  其中 **10~25° 那档就是"本该直、却画成波浪"**（真拐弯一般是 45° 或 90°）。

用法：
    python tools/_diag_smoothness.py            # 全部线
    python tools/_diag_smoothness.py 11 7 9     # 只看这几条
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication                          # noqa: E402
from ui.map_view import build_line_points_ex                        # noqa: E402
from ui import metro_render as MR                                   # noqa: E402


def main():
    app = QApplication.instance() or QApplication(sys.argv[:1])      # noqa: F841
    import core.data_manager as CDM
    ST = json.loads(CDM.STATIONS_FILE.read_text(encoding="utf-8"))["stations"]
    LINES = json.loads(CDM.LINES_FILE.read_text(encoding="utf-8"))["lines"]
    want = [a for a in sys.argv[1:] if not a.startswith("-")]

    print("=" * 78)
    print("线路平顺度：渲染点列里的转角分布（10~25° 那档 = 本该直却画成波浪）")
    print("=" * 78)
    print("%-6s %-8s | %6s %6s %6s %6s | %s" % ("线", "点数", "<10°", "10~25", "25~45", "≥45°", "点距中位"))
    print("-" * 78)
    tot = [0, 0, 0, 0]
    for l in LINES:
        lid = str(l.get("id"))
        if want and lid not in want:
            continue
        seq = [n for n in (l.get("stations") or []) if n in ST]
        if len(seq) < 2:
            continue
        pts, ebl = build_line_points_ex(lid, seq, ST)
        tag = MR.octilinear_waypoints_tagged(pts, ebl)
        Q = [p for p, _ in tag]
        turns = []
        edge = []
        for i in range(1, len(Q) - 1):
            v1 = (Q[i].x() - Q[i - 1].x(), Q[i].y() - Q[i - 1].y())
            v2 = (Q[i + 1].x() - Q[i].x(), Q[i + 1].y() - Q[i].y())
            l1 = math.hypot(*v1)
            l2 = math.hypot(*v2)
            if l1 < 1e-6 or l2 < 1e-6:
                continue
            edge.append(l2)
            c = (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)
            turns.append(math.degrees(math.acos(max(-1.0, min(1.0, c)))))
        b = [sum(1 for t in turns if t < 10),
             sum(1 for t in turns if 10 <= t < 25),
             sum(1 for t in turns if 25 <= t < 45),
             sum(1 for t in turns if t >= 45)]
        for k in range(4):
            tot[k] += b[k]
        med = sorted(edge)[len(edge) // 2] if edge else 0
        print("%-6s %-8d | %6d %6d %6d %6d | %.0f"
              % (lid, len(Q), b[0], b[1], b[2], b[3], med))
    print("-" * 78)
    print("合计：<10° %d   10~25° %d   25~45° %d   ≥45° %d  （转角合计 %d）"
          % (tot[0], tot[1], tot[2], tot[3], sum(tot)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
