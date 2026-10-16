"""
_probe_station_on_line.py —— 「站点到底在不在线上」量化探针（不启动 GUI）

背景：用户报告「很多站点放大后发现并没有在轨道的线上」。

做法：完全按 App 的构建方式重建线路路径
      （rebuild_lines → MetroLineItem.set_points(pts, smooth=True)
        → build_octilinear_path → _octilinear_waypoints → build_rounded_polyline）
      然后把路径**压平成折线**（QPainterPath.toSubpathPolygons 是自适应细分，
      对开口子路径同样有效），逐站算「点到折线的最短距离」= 偏离量。

为什么不能用 pointAtPercent 采样：每次调用都要按弧长查表，O(n) 一次，
N 个采样点 = O(N²)，20 条线会跑很久；压平成折线后是 O(顶点数)，且更准。

用法：
    python _probe_station_on_line.py                      # 现状（= App 真实行为）
    python _probe_station_on_line.py --old-fillet-all      # 对照：旧行为，所有顶点都倒圆角
    python _probe_station_on_line.py --data-dir ..\\..\\软件\\data   # 量打包版那份数据
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath

from ui.metro_render import (  # noqa: E402
    _octilinear_waypoints, build_rounded_polyline, build_octilinear_path,
)

DATA_DIR = SRC / "data"


# ---------------------------------------------------------------- 基础几何
def point_seg_dist(p: QPointF, a: QPointF, b: QPointF) -> float:
    """点到线段的最短距离。"""
    vx, vy = b.x() - a.x(), b.y() - a.y()
    wx, wy = p.x() - a.x(), p.y() - a.y()
    L2 = vx * vx + vy * vy
    if L2 < 1e-12:
        return math.hypot(wx, wy)
    t = (wx * vx + wy * vy) / L2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(wx - t * vx, wy - t * vy)


def dist_to_path(p: QPointF, path: QPainterPath) -> float:
    """点到路径的最短距离（先把路径自适应压平成折线）。"""
    polys = path.toSubpathPolygons()
    best = float("inf")
    for poly in polys:
        n = poly.count()
        if n == 0:
            continue
        if n == 1:
            d = math.hypot(p.x() - poly[0].x(), p.y() - poly[0].y())
            best = min(best, d)
            continue
        for i in range(n - 1):
            d = point_seg_dist(p, poly[i], poly[i + 1])
            if d < best:
                best = d
    return best


# ---------------------------------------------------------------- 数据载入
def load():
    lines = json.loads((DATA_DIR / "lines.json").read_text(encoding="utf-8"))["lines"]
    stations = json.loads((DATA_DIR / "stations.json").read_text(encoding="utf-8"))["stations"]
    return lines, stations


# ---------------------------------------------------------------- 路径构建
def build_path_current(pts):
    """现状：= App 真实行为（站点不倒圆角，45°折点倒圆角）。"""
    return build_octilinear_path(pts)


def build_path_old_fillet_all(pts):
    """复现旧行为：所有顶点（含站点）一律倒圆角。"""
    return build_rounded_polyline(_octilinear_waypoints(pts), radius=170.0)


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-fillet-all", action="store_true",
                    help="对照模式：复现旧的「所有顶点都倒圆角」")
    ap.add_argument("--data-dir", default=None,
                    help="量哪份数据（默认 源码/data；打包版是 软件/data）")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    global DATA_DIR
    if args.data_dir:
        DATA_DIR = Path(args.data_dir).resolve()
    print("数据目录:", DATA_DIR)

    lines, stations = load()
    builder = build_path_old_fillet_all if args.old_fillet_all else build_path_current

    rows = []          # (dev, line_id, st_name, is_transfer)
    for line in lines:
        lid = line["id"]
        seq = line.get("stations") or []
        pts, names = [], []
        for name in seq:
            st = stations.get(name)
            if not st:
                continue
            pts.append(QPointF(float(st.get("x", 0)), float(st.get("y", 0))))
            names.append(name)
        if len(pts) < 2:
            continue
        path = builder(pts)
        for name, p in zip(names, pts):
            dev = dist_to_path(p, path)
            rows.append((dev, lid, name, bool(stations[name].get("is_transfer"))))

    n = len(rows)
    devs = [r[0] for r in rows]
    bands = [(0.5, ">0.5"), (2.0, ">2"), (5.0, ">5"), (20.0, ">20"), (60.0, ">60")]
    print("=" * 72)
    print("模式:", "旧的「所有顶点都倒圆角」（对照）" if args.old_fillet_all
          else "现状 = App 真实行为（站点不倒圆角）")
    print(f"参与统计的「线路-站点」条目: {n}   不同站点数: {len({r[2] for r in rows})}")
    print("-" * 72)
    print(f"偏离量(scene单位)  平均 {sum(devs)/n:8.2f}   中位 {sorted(devs)[n//2]:8.2f}"
          f"   最大 {max(devs):8.2f}")
    for th, lab in bands:
        c = sum(1 for d in devs if d > th)
        print(f"  偏离 {lab:>5} : {c:4d} 条  ({100.0*c/n:5.1f}%)")
    print("-" * 72)

    # 换算成「屏幕像素」看肉眼可见性（视口 874 宽，fit 缩放约 0.1）
    for scale, tag in ((0.10, "缩到最小"), (1.0, "1:1"), (8.0, "放到最大")):
        worst = max(devs) * scale
        over1 = sum(1 for d in devs if d * scale > 1.0)
        print(f"  scale={scale:<5} {tag:<8} 最大偏离 {worst:7.1f} 屏幕px   "
              f"偏离>1px 的条目 {over1:4d} / {n}")

    print("-" * 72)
    rows.sort(reverse=True)
    print(f"最严重的 {args.top} 条：")
    print(f"  {'偏离':>8}  {'线路':<4} {'站点':<12} 换乘")
    for dev, lid, name, tr in rows[:args.top]:
        print(f"  {dev:8.2f}  {lid:<4} {name:<12} {'★' if tr else ''}")
    print("=" * 72)


if __name__ == "__main__":
    main()
