# -*- coding: utf-8 -*-
"""_chk_zoom_to_station.py —— 回归：「定位/搜索到站点」必须真的把该站放在视口中心。

怎么发现的：做 v2.5.4 的对照截图时，发现 `zoom_to_station("南山", 4.0)` 之后
南山跑到 x=-26（视口宽 874，正中心应是 437）—— **站点被推出屏幕外**。

根因：`self.centerOn(item)` 用的是 `centerOn(QGraphicsItem*)` 重载，
它居中在 **item.sceneBoundingRect() 的中心**，而站点的包围盒 = 圆点 + 旁边的站名，
于是居中偏到"圆点+站名"整体的中心，圆点被挤到左边。
而且调用点还**早于** `_apply_station_scale_all()`，此时图元还是**旧缩放**的几何：
实测标签缩放 = 1/0.1055 → 包围盒宽 445 场景单位 → 中心比圆点右偏 **115.66 场景单位**，
在 4 倍缩放下 = **463 屏幕px**。修法就是改成 `centerOn(QPointF(item.pos()))`。

影响面（都是用户会点到的入口）：
    · 右侧信息面板 / 搜索候选 → `MainWindow._locate_station()` → zoom_to_station
    · 搜索框回车、双击站点、键盘上下选站

运行：
    python tools/_chk_zoom_to_station.py
    python tools/_chk_zoom_to_station.py --mutate-center-on-item   # 应当失败
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

PASS = FAIL = 0
TOL = 3.0        # 屏幕像素：允许滚动条整数取值的取整误差
SCALES = (1.0, 1.6, 4.0, 8.0)
# 兼顾：换乘站/普通站、站名 2 字与 4 字、站名摆在左边与右边
CASES = ("南山", "会展中心", "少年宫", "华强北", "妈湾", "光明", "机场东", "石厦")


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}   {detail}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}   {detail}")


def mutate_center_on_item(mv) -> None:
    """把 zoom_to_station 换回"centerOn(item)"的旧写法（变异测试用）。"""
    def old_zoom_to_station(station_id: str, target_scale: float = 1.6) -> None:
        item = mv.station_items.get(station_id)
        if not item:
            return
        mv.resetTransform()
        mv.scale(target_scale, target_scale)
        mv._scale = target_scale
        mv._refresh_scene_rect()
        mv.centerOn(item)              # ★ 旧写法：居中的是包围盒中心
        mv._sync_zoom_state()
        mv._apply_line_width()
        mv._apply_station_scale_all()
        mv.zoom_changed.emit(mv._scale)
    mv.zoom_to_station = old_zoom_to_station


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate-center-on-item", action="store_true")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    for _ in range(4):
        app.processEvents()
    win.dm.save = lambda *a, **k: None     # 不许写盘
    mv = win.map_view
    if args.mutate_center_on_item:
        mutate_center_on_item(mv)

    vp = mv.viewport()
    cx, cy = vp.width() // 2, vp.height() // 2
    print("=" * 78)
    print("视口 %dx%d  理想中心 (%d, %d)%s"
          % (vp.width(), vp.height(), cx, cy,
             "   【变异：centerOn(item) 旧写法】" if args.mutate_center_on_item else ""))

    cases = [s for s in CASES if s in mv.station_items]
    all_scale_ok = True
    for s in SCALES:
        worst = 0.0
        worst_sid = ""
        n_off = 0
        for sid in cases:
            mv.zoom_to_station(sid, s)
            for _ in range(3):
                app.processEvents()
            p = mv.mapFromScene(mv.station_items[sid].pos())
            d = max(abs(p.x() - cx), abs(p.y() - cy))
            if d > worst:
                worst, worst_sid = d, sid
            if d > TOL:
                n_off += 1
        all_scale_ok = all_scale_ok and n_off == 0
        ok("scale=%.1f：%d 个站的圆点都落在视口中心（<=%gpx）"
           % (s, len(cases), TOL), n_off == 0,
           "最大偏差 %.1fpx（%s），超标 %d/%d"
           % (worst, worst_sid, n_off, len(cases)))

    # 再单独钉一条"必须真的在屏幕里"，防止容差放宽后站点跑到视口外还判过
    mv.zoom_to_station(cases[0], 4.0)
    for _ in range(3):
        app.processEvents()
    p = mv.mapFromScene(mv.station_items[cases[0]].pos())
    inside = vp.rect().contains(p)
    ok("圆点必须真的落在视口矩形内", inside,
       "%s 在 (%d, %d)，视口 %dx%d" % (cases[0], p.x(), p.y(), vp.width(), vp.height()))

    print("=" * 78)
    print("通过 %d 项，失败 %d 项" % (PASS, FAIL))
    if args.mutate_center_on_item:
        print("（变异模式：这里**应该**看到失败，才证明本回归真的抓得住这个 bug）")
    elif FAIL == 0:
        print("全部通过 ✅")
    print("=" * 78)
    win.close()
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
