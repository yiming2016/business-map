# -*- coding: utf-8 -*-
"""_chk_station_on_line.py —— 回归：「站点必须压在轨道线上」。

用户报告：「很多站点放大后发现并没有在轨道的线上」。

根因（见 ui/metro_render.build_octilinear_path 的长注释）：线路是八向布线出来
的折线，原来**每个顶点都倒圆角**（radius=170）。倒圆角 = 把拐角削掉，而站点
恰好都是拐角 → 线从圆点底下挪走。实测偏离最大 78 场景单位，放到最大（scale=8）
就是 **624 屏幕px**，圆点直接飘到线外。

本回归分两层：

  A 几何层（活图元）—— 直接量**场景里真实那个 MetroLineItem 的 path()**，
    不重新推导路径。对每条线上的每一站算"点到路径最短距离"。
    要求 < 0.5 场景单位（非零只留浮点/压平误差的余量）。
    这一层能抓"布线算法被改回倒圆角"。

  B 像素层（端到端）—— 把**所有站点图元隐藏**（这样画面上只剩线路和背景），
    抓视口像素，对若干个原来最离谱的站点，量"投影中心到最近一个线路像素"
    的距离。要求 <= 3.5 屏幕px（线宽 4.6px 的一半 = 2.3，再留抗锯齿余量）。
    这一层能抓"几何对了但渲染错位"（变换/缓存/层级之类）。

  --mutate-old-geometry：故意把布线换成"全部倒圆角"的旧实现，
    用来证明本回归真的抓得住这个 bug（变异测试）。此时应当**失败**。

运行：
    python tools/_chk_station_on_line.py
    python tools/_chk_station_on_line.py --mutate-old-geometry   # 应当失败
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from ui import metro_render as MR
from ui.main_window import MainWindow

PASS = FAIL = 0
GEO_TOL = 0.5          # 场景单位：点到线路路径的允许偏离
PIX_TOL = 3.5          # 屏幕像素：圆点中心到最近线路像素的允许距离
PIX_SCALES = (1.0, 3.0, 8.0)
PIX_RADIUS = 40        # 只在中心 ±40px 内找线路像素（放心：最近站距 >> 80px）


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}   {detail}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}   {detail}")


# ---------------------------------------------------------------- 几何
def point_seg_dist(p: QPointF, a: QPointF, b: QPointF) -> float:
    vx, vy = b.x() - a.x(), b.y() - a.y()
    wx, wy = p.x() - a.x(), p.y() - a.y()
    L2 = vx * vx + vy * vy
    if L2 < 1e-12:
        return math.hypot(wx, wy)
    t = (wx * vx + wy * vy) / L2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(wx - t * vx, wy - t * vy)


def dist_to_path(p: QPointF, path) -> float:
    """点到路径最短距离（路径先自适应压平成折线）。"""
    best = float("inf")
    for poly in path.toSubpathPolygons():
        n = poly.count()
        if n == 0:
            continue
        if n == 1:
            best = min(best, math.hypot(p.x() - poly[0].x(), p.y() - poly[0].y()))
            continue
        for i in range(n - 1):
            d = point_seg_dist(p, poly[i], poly[i + 1])
            if d < best:
                best = d
    return best


# ---------------------------------------------------------------- 像素
def nearest_ink_px(img, cx: float, cy: float, radius: int, bg=(247, 249, 251)):
    """中心 → 最近一个"非背景"像素的距离（像素）。

    ★ 为什么要先隐藏所有站点：站点的白色填充 + 同色描边会自己造出一圈
      "线路色"像素，量出来永远是 0，等于没测。隐藏后画面上只剩线路
      → 最近墨迹就是线路本体。
    """
    w, h = img.width(), img.height()
    x0 = max(0, int(cx) - radius)
    x1 = min(w - 1, int(cx) + radius)
    y0 = max(0, int(cy) - radius)
    y1 = min(h - 1, int(cy) + radius)
    best = float("inf")
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            c = img.pixelColor(x, y)
            if (abs(c.red() - bg[0]) > 30 or abs(c.green() - bg[1]) > 30
                    or abs(c.blue() - bg[2]) > 30):
                d = math.hypot(x - cx, y - cy)
                if d < best:
                    best = d
    return best


# ---------------------------------------------------------------- 变异
def mutate_old_geometry() -> None:
    """把布线换回"每个顶点都倒圆角"的旧实现（含站点）。"""
    def old_path(points, radius=170.0):
        if len(points) < 2:
            return MR.build_rounded_polyline(points, radius)
        return MR.build_rounded_polyline(MR._octilinear_waypoints(points), radius)
    MR.build_octilinear_path = old_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate-old-geometry", action="store_true")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    app.processEvents()
    mv = win.map_view
    # ★ 测试绝不写盘：MainWindow.closeEvent 里会 dm.save()，一跑测试就把
    #   源码/data/ 下的 stations.json / lines.json 重写一遍（内容虽然一致，
    #   但 mtime 变化 + 生成 .bak，容易让人误以为数据被改了）。
    win.dm.save = lambda *a, **k: None
    if args.mutate_old_geometry:
        mutate_old_geometry()
        mv.rebuild_lines()
        app.processEvents()

    print("=" * 78)
    print("视口 %dx%d  站点 %d  线路 %d%s"
          % (mv.viewport().width(), mv.viewport().height(), len(mv.station_items),
             len(mv.line_items),
             "   【变异：旧布线/全部倒圆角】" if args.mutate_old_geometry else ""))

    # ---------- A 几何层：直接用场景里真实的路径 ----------
    print("\nA 几何：每一站到「所在线路」路径的距离"
          "（量的是场景里真实的 MetroLineItem.path()）")
    from core.data_manager import get_data_manager
    dmm = get_data_manager()
    rows = []
    for line in dmm.all_lines():
        lid = line["id"]
        item = mv.line_items.get(lid)
        if item is None:
            continue
        path = item.path()
        for name in (line.get("stations") or []):
            it = mv.station_items.get(name)
            if it is None:
                continue
            # ★★ v2.6.20 判据前提变了：换乘站的每条线现在**各占一条走廊**
            #    （偏移量从原图逐站量出，见 data/stations.json 的 `lanes`），
            #    所以这条线本来就**不过站中心**，而是过"站中心 + 该线偏移"。
            #    容差 = 该线在该站的偏移长度 + 原来的精确容差。
            # ★★ v2.6.21 判据前提又变了一条：**同名双站体**的站（湖贝/红岭南/
            #    清湖/坪山中心）主坐标只代表其中一个站体，属于另一条线的站体
            #    在 `alt_bodies` 里。那条线走的是**它自己的站体**，离主坐标
            #    90~105 场景单位 —— 这是**设计如此**，不是没落在线上。
            #    ⇒ 必须先换成"该站该线真正的站体坐标"再量。
            x, y = float(it.data.get("x", 0)), float(it.data.get("y", 0))
            for b in (it.data.get("alt_bodies") or []):
                if str(b.get("line") or "") == str(lid):
                    try:
                        x, y = float(b["x"]), float(b["y"])
                    except (KeyError, TypeError, ValueError):
                        pass
                    break
            d = (it.data.get("lanes") or {}).get(str(lid))
            tol = GEO_TOL
            if d:
                tol += math.hypot(float(d[0]), float(d[1]))
            rows.append((dist_to_path(QPointF(x, y), path), lid, name, tol))
    if not rows:
        ok("A 找到了线路与站点", False, "一条线都没匹配上")
    else:
        over = [(r[0], r[1], r[2]) for r in rows if r[0] > r[3]]
        n_over = len(over)
        worst_rows = sorted(rows, key=lambda r: -(r[0] - r[3]))[:5]
        detail = ", ".join("%s/%s=%.2f(容差%.1f)" % (r[1], r[2], r[0], r[3])
                           for r in worst_rows)
        ok("A 全部 %d 条「线路-站点」都落在该站该线的走廊上（偏移+%g 场景单位内）"
           % (len(rows), GEO_TOL),
           n_over == 0,
           "超标 %d 条   最严重：%s" % (n_over, detail))

    # ---------- B 像素层：端到端 ----------
    print("\nB 像素：隐藏站点后抓屏，量「圆点中心 → 最近线路像素」")
    # ★ 固定用"改动前偏离最严重的 6 个站"来复检，而不是用当前跑出来的最差 ——
    #   修好之后所有站都变成 0，靠排序挑出来的只是一批**随机**站（并列），
    #   那样 B 层就失去了针对性和可比性。
    #   这几个站名/数值来自改动前的基线实测（tools/_probe_station_on_line.py）：
    #     南山(12线)=78.1、石鼓(13线)=60.9、南山(11线)=60.6、海上田园南=42.1、
    #     西丽=36.4、老街=34.8 场景单位
    worst = [n for n in ("南山", "石鼓", "海上田园南", "西丽", "老街", "岗厦北")
             if n in mv.station_items]
    # 隐藏所有站点，画面只剩线路 + 背景
    for it in mv.station_items.values():
        it.setVisible(False)
    app.processEvents()

    dpr = mv.devicePixelRatioF()
    all_bad = 0
    for s in PIX_SCALES:
        vals = []
        for sid in worst:
            mv.zoom_to_station(sid, s)
            QApplication.processEvents()
            app.processEvents()
            it = mv.station_items[sid]
            vp = mv.viewport()
            p = mv.mapFromScene(it.pos())
            img = vp.grab().toImage()
            # vp.grab() 是设备像素；mapFromScene 是逻辑坐标 → 乘 dpr
            # ★ v2.6.20：换乘站的线在走廊上（偏移最多 ~58 场景单位），
            #   所以搜索半径要按走廊偏移放大 —— 老街在 scale=3 时线离圆点 81px，
            #   仍用固定的 ±40px 就一个线路像素都找不到（量出 inf 的假失败）。
            off = max([math.hypot(float(v[0]), float(v[1]))
                       for v in (it.data.get("lanes") or {}).values()] or [0.0])
            search_r = int(round((PIX_RADIUS + off * s) * dpr))
            d = nearest_ink_px(img, (p.x() + 0.5) * dpr, (p.y() + 0.5) * dpr,
                               search_r)
            vals.append((d, sid, off * s + PIX_TOL))
        vals.sort(reverse=True)
        mx, mx_sid, _mt = vals[0]
        bad = sum(1 for v, _n, t in vals if v > t)
        all_bad += bad
        ok("B scale=%.1f：6 个复检站都落在自家走廊上（<= 走廊偏移×缩放 %gpx + %gpx）"
           % (s, s, PIX_TOL),
           bad == 0,
           "最大 %.1fpx（%s），超标 %d/%d   明细 %s"
           % (mx, mx_sid, bad, len(vals),
              " ".join("%s=%.1f(容差%.1f)" % (n, v, t) for v, n, t in vals)))

    for it in mv.station_items.values():
        it.setVisible(True)
    app.processEvents()

    print("\n" + "=" * 78)
    print("通过 %d 项，失败 %d 项" % (PASS, FAIL))
    if args.mutate_old_geometry:
        print("（变异模式：这里**应该**看到失败，才证明本回归真的抓得住这个 bug）")
    elif FAIL == 0:
        print("全部通过 ✅")
    print("=" * 78)
    win.close()
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
