# -*- coding: utf-8 -*-
"""
tools/_probe_v269_labels.py
===========================
v2.6.9 站名避让线路 + 换乘图标体检。

量四件事：
  1. **有多少站名压在线路线条里**（用户报的 bug）
     —— 站名矩形 vs 线路中心线（外扩半个线宽 = 线实际占的墨迹）求交。
     开/关 `LABEL_AVOID_LINES` 各跑一遍，看差值（变异测试就靠这个）
  2. 排版耗时有没有被拖垮（`_update_label_visibility`）
  3. 线路索引本身的规模（段数 / 建索引耗时）—— 判断会不会踩性能坑
  4. 换乘站图标：确认 `is_transfer` 的站走的是新画法（三段半径）

★ 别加 QT_QPA_PLATFORM=offscreen（字体度量会假）。
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFont                            # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

import ui.map_view as MV                                   # noqa: E402
from ui.main_window import MainWindow                      # noqa: E402
from ui.metro_render import (                              # noqa: E402
    SCREEN_LINE_W, TRANSFER_RING_RATIO, TRANSFER_CORE_RATIO,
    SCREEN_TRANSFER_R, SCREEN_NORMAL_R,
)


def pump(n: int = 14) -> None:
    for _ in range(n):
        QApplication.processEvents()


def set_scale(mv, scale) -> None:
    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    pump(8)
    mv._invalidate_nn()
    mv._update_label_visibility()
    pump(10)


def line_overlap_count(mv) -> tuple:
    """(可见站名数, 压到线的站名数, 压线占比%)"""
    from ui.metro_render import LineSegIndex
    k = 1.0 / max(mv._scale, 0.01)
    idx = LineSegIndex()
    cell = 60.0 * k
    idx.build(mv.line_items, cell, -1)        # -1 = 强制重建（不用缓存）
    ink = SCREEN_LINE_W * 0.5 * k             # 线本身占的墨迹半宽
    shown = [it for it in mv.station_items.values() if it._label_on]
    hit = deep = 0
    for it in shown:
        r = it.label_scene_rect(it.label_side())
        if r.width() <= 0.1:
            continue
        ln = idx.hit_length(r, ink)
        if ln > 0:
            hit += 1
            # ★ "严重压线"：线穿过站名的长度 ≥ 站名短边的一半
            #   （= 线基本从字中间穿过去，才是用户说的"融进线条里"）
            if ln >= min(r.width(), r.height()) * 0.5:
                deep += 1
    n = len(shown)
    return n, hit, (100.0 * hit / n if n else 0.0), deep


def main() -> int:
    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(40)
    mv = win.map_view
    floor = mv._min_scale_for_viewport()

    print("\n===== 0 线路几何索引规模 =====")
    from ui.metro_render import LineSegIndex
    t0 = time.perf_counter()
    idx = LineSegIndex()
    idx.build(mv.line_items, 120.0, -1)
    t_build = (time.perf_counter() - t0) * 1000.0
    print("      线段数        : %d" % len(idx.segs))
    print("      网格格子数    : %d" % len(idx.buckets))
    print("      建索引耗时    : %.1f ms" % t_build)
    biggest = max(len(v) for v in idx.buckets.values()) if idx.buckets else 0
    avg = (sum(len(v) for v in idx.buckets.values()) / len(idx.buckets)) if idx.buckets else 0
    print("      每格段数      : 平均 %.1f，最多 %d" % (avg, biggest))

    print("\n===== 1 站名压线统计（开 / 关 避让 各一遍）=====")
    for flag in (False, True):
        MV.LABEL_AVOID_LINES = flag
        print("      --- LABEL_AVOID_LINES = %s ---" % flag)
        for s in (floor, 0.16, 0.30, 1.0):
            set_scale(mv, s)
            t0 = time.perf_counter()
            mv._update_label_visibility()
            cost = (time.perf_counter() - t0) * 1000.0
            n, hit, pct, deep = line_overlap_count(mv)
            print("         缩放 %6.3f：站名 %3d，压线 %3d（%5.1f%%），"
                  "其中严重 %3d（%5.1f%%），排版 %.1fms"
                  % (s, n, hit, pct, deep, 100.0 * deep / n if n else 0.0, cost))

    print("\n===== 1b 呼吸量 LABEL_LINE_AVOID_PX 取多少好（缩到最小那一档最吃紧）=====")
    MV.LABEL_AVOID_LINES = True
    for pad_px in (0.0, 0.5, 1.5, 3.0):
        MV.LABEL_LINE_AVOID_PX = pad_px
        set_scale(mv, floor)
        n, hit, pct, deep = line_overlap_count(mv)
        print("      pad=%.1fpx：站名 %3d，压线 %3d（%5.1f%%），严重 %3d（%5.1f%%）"
              % (pad_px, n, hit, pct, deep, 100.0 * deep / n if n else 0.0))
    MV.LABEL_LINE_AVOID_PX = 1.5

    print("\n===== 2 排版耗时（中位，各 3 遍）=====")
    MV.LABEL_AVOID_LINES = True
    worst = 0.0
    for s in (floor, 0.16, 0.30, 1.0):
        set_scale(mv, s)
        c = []
        for _ in range(3):
            t0 = time.perf_counter()
            mv._update_label_visibility()
            c.append((time.perf_counter() - t0) * 1000.0)
        worst = max(worst, statistics.median(c))
        print("      缩放 %6.3f：%.1f ms" % (s, statistics.median(c)))
    print("      ⇒ 最慢 %.1f ms（旧版基线 ~60ms，阈值 90ms）" % worst)

    print("\n===== 3 换乘站图标 =====")
    tr = [it for it in mv.station_items.values() if it.is_transfer]
    print("      换乘站数      : %d / %d" % (len(tr), len(mv.station_items)))
    print("      普通站半径    : %.2f px   换乘站外圈 %.2f px" % (SCREEN_NORMAL_R, SCREEN_TRANSFER_R))
    print("      内环半径      : %.2f px（比例 %.2f）" % (SCREEN_TRANSFER_R * TRANSFER_RING_RATIO,
                                                     TRANSFER_RING_RATIO))
    print("      核心半径      : %.2f px（比例 %.2f）" % (SCREEN_TRANSFER_R * TRANSFER_CORE_RATIO,
                                                     TRANSFER_CORE_RATIO))
    # 三段必须真的分得开（否则画出来是一坨黑饼）
    outer_in = SCREEN_TRANSFER_R - 1.8 * 0.5
    ring_out = SCREEN_TRANSFER_R * TRANSFER_RING_RATIO + 1.1 * 0.5
    print("      外圈内缘 %.2f px > 内环外缘 %.2f px ⇒ 白环带宽 %.2f px"
          % (outer_in, ring_out, outer_in - ring_out))

    win.close()
    pump()
    return 0


if __name__ == "__main__":
    sys.exit(main())
