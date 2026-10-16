# -*- coding: utf-8 -*-
"""只读：量"站点/折点到画出来的曲线"的最短距离（场景单位）。

v2.6.26 前：站点处一律走尖角 ⇒ 距离 ≈ 0，但线路在那里是硬拐角（用户：不够圆润）。
v2.6.26 后：站点处也倒圆角 + 控制点外移 ⇒ 线路圆了，**距离仍然必须 ≈ 0**。

用法:
    python tools/_probe_station_on_curve.py            # 新写法
    METROEDITOR_NO_STATION_CURVE=1 python ...          # 退回"站点走尖角"（对照）
"""
import os
import sys
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication                 # noqa: E402
from PySide6.QtCore import QPointF                         # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)    # noqa: F841

from ui.metro_render import build_octilinear_path          # noqa: E402
from ui.map_view import build_line_points_ex, elbow_sides  # noqa: E402

N = 4000


def path_samples(path):
    return [(path.pointAtPercent(i / float(N)).x(),
             path.pointAtPercent(i / float(N)).y()) for i in range(N + 1)]


def main():
    st = json.load(open(ROOT / "data" / "stations.json", encoding="utf-8"))["stations"]
    ln = json.load(open(ROOT / "data" / "lines.json", encoding="utf-8"))
    lines = ln["lines"] if isinstance(ln, dict) and "lines" in ln else ln
    _eb = elbow_sides()
    old = os.environ.get("METROEDITOR_NO_STATION_CURVE", "0") == "1"
    print("写法：%s" % ("旧（站点走尖角）" if old else "新（站点处倒圆角 + 控制点外移）"))

    worst = []
    allmax = 0.0
    for L in lines:
        lid = str(L.get("id") or L.get("line_id") or "")
        seq = L.get("stations") or []
        if len(seq) < 3:
            continue
        pts, ebl = build_line_points_ex(lid, seq, st)
        if len(pts) < 3:
            continue
        path = build_octilinear_path([QPointF(p.x(), p.y()) for p in pts], elbows=ebl)
        sp = path_samples(path)
        for p in pts:
            x, y = p.x(), p.y()
            best = min((sx - x) ** 2 + (sy - y) ** 2 for sx, sy in sp) ** 0.5
            if best > allmax:
                allmax = best
            worst.append((best, lid, x, y))
    worst.sort(reverse=True)
    ds = [w[0] for w in worst]
    print("  点数 %d" % len(ds))
    print("  到曲线距离：最大 %.2f  平均 %.2f  中位 %.2f" %
          (ds[0], sum(ds) / len(ds), ds[len(ds) // 2]))
    print("  最差 8 个：")
    for d, lid, x, y in worst[:8]:
        print("    %-4s (%7.0f,%7.0f)  %.2f" % (lid, x, y, d))
    n_over = len([d for d in ds if d > 2.0])
    print("  > 2 场景单位的点：%d 个" % n_over)


if __name__ == "__main__":
    main()
