# -*- coding: utf-8 -*-
"""_probe_layout_cost.py —— 站名防重叠排版(_update_label_visibility)的耗时。

为什么要单独量：_chk_label_density.py 的 E 段只取 4 次采样的**最大值**，
阈值 60ms，属于噪声敏感项（本次实测 60.2ms 擦线）。这里：
  · 每个缩放点重复 N 次，报中位/最大，抗噪声；
  · 分别量「新字号策略」与「旧字号策略（>0.30 一律 12px）」，
    把两个变化的代价分开：
      (a) 字号变大 → 碰撞变多 → 贪心排版多试几个方向 → 变慢（这是预期的代价）
      (b) 标签坐标体系改成"局部单位=屏幕像素" → 应该几乎免费

用法：python tools/_probe_layout_cost.py
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from ui import metro_render as MR
from ui.main_window import MainWindow

SCALES = [0.093, 0.16, 0.30, 1.0, 2.0, 4.0, 8.0]
REPEAT = 9


def old_font_px(view_scale: float) -> float:
    """改动前的字号策略：只在缩小方向收窄，放大方向恒为 12px。"""
    s = max(view_scale, 1e-4)
    if s >= 0.30:
        return 12.0
    t = (s - 0.08) / 0.22
    t = min(max(t, 0.0), 1.0)
    return 10.0 + 2.0 * t


def measure(mv, s: float) -> tuple[float, float, int]:
    mv.zoom_to_station(next(iter(mv.station_items)), s)
    QApplication.processEvents()
    t0 = time.perf_counter()
    mv._update_label_visibility()
    warm = (time.perf_counter() - t0) * 1000.0
    ts = []
    for _ in range(REPEAT):
        t0 = time.perf_counter()
        mv._update_label_visibility()
        ts.append((time.perf_counter() - t0) * 1000.0)
    shown = sum(1 for it in mv.station_items.values() if it.is_label_visible())
    return warm, statistics.median(ts), shown


def run(tag: str, mv):
    print("-" * 72)
    print(tag)
    print("  %6s %10s %10s %10s %8s" % ("scale", "首发ms", "中位ms", "最大ms", "显示数"))
    out = {}
    for s in SCALES:
        warm, med, shown = measure(mv, s)
        out[s] = (warm, med, shown)
        print("  %6.2f %10.1f %10.1f %10.1f %8d"
              % (s, warm, med, max(med, warm), shown))
    return out


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    app.processEvents()
    mv = win.map_view

    print("=" * 72)
    print("站名排版耗时（视口 %dx%d，站点 %d，每点重复 %d 次）"
          % (mv.viewport().width(), mv.viewport().height(),
             len(mv.station_items), REPEAT))
    newf = MR.effective_font_px
    a = run("【新】字号随放大变大（10 → 20px）", mv)

    MR.effective_font_px = old_font_px
    b = run("【旧】放大方向恒 12px（把字号因素隔离掉）", mv)
    MR.effective_font_px = newf
    print("=" * 72)
    print("对照（中位耗时，ms）：")
    print("  %6s %10s %10s %10s" % ("scale", "新", "旧", "差"))
    for s in SCALES:
        print("  %6.2f %10.1f %10.1f %+10.1f"
              % (s, a[s][1], b[s][1], a[s][1] - b[s][1]))
    print("=" * 72)


if __name__ == "__main__":
    main()
