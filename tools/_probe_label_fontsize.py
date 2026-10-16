# -*- coding: utf-8 -*-
"""_probe_label_fontsize.py —— 量「放大后站名到底变大还是变小」。

用户报告：「放大后反而文字还变小了」。

站名尺寸在代码里是这么定的（ui/metro_render.py + StationDotItem）：
    screen_font_px = effective_font_px(scale)      # 屏幕字号（设计成"恒定 12px"）
    scene_px       = round(screen_font_px / scale) # 换算成场景字号（整数，QFont 只收整数）
    实际屏幕字号    = scene_px * scale              # ← 量化误差在这里被放大回来

所以只要 round() 取整，实际屏幕字号就会随 scale 呈**锯齿**：本探针就是把这个
锯齿实测出来（直接读图元真实的 font().pixelSize()，不靠公式推）。

同时测：
  · 真实字形的墨迹高度（走 HaloLabel._text_path 的 boundingRect），
    避免"字号变了但字没变"这种误判；
  · 圆点直径，用来判断"站名相对地图是不是显得小"。

运行：python tools/_probe_label_fontsize.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.metro_render import effective_font_px

SCALES = [0.08, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.60, 1.00, 1.60,
          2.00, 2.50, 3.00, 3.50, 4.00, 4.50, 5.00, 6.00, 7.00, 8.00]

W = 88


def R(s: str, n: int) -> str:
    return str(s).rjust(n)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    app.processEvents()
    mv = win.map_view

    norm = next(it for it in mv.station_items.values() if not it.is_transfer)
    tran = next(it for it in mv.station_items.values() if it.is_transfer)

    print("=" * W)
    print("视口 " + str(mv.viewport().width()) + "x" + str(mv.viewport().height())
          + "   站点数 " + str(len(mv.station_items)))
    print("-" * W)
    print(R("scale", 6) + " | " + R("eff()", 6) + " " + R("标签px", 6) + " "
          + R("真实屏幕px", 10) + " | " + R("普通站字墨高", 13) + " "
          + R("换乘站字墨高", 13) + " | " + R("圆点直径px", 10))
    print("-" * W)

    rows = []
    for s in SCALES:
        mv.zoom_to_station(norm.station_id, s)
        app.processEvents()
        real_s = mv._scale
        # ★ 标签局部单位 == 屏幕像素，所以局部尺寸 × label_scale × view_scale
        #   才是屏幕尺寸（label_scale 由 apply_view_scale 设为 1/view_scale）
        k2s = norm.label_scale() * real_s
        px = norm.label.font().pixelSize()
        screen_px = px * k2s
        ink = norm.label._text_path().boundingRect().height() * k2s
        ink_t = tran.label._text_path().boundingRect().height() * k2s
        dot_d = norm.screen_radius() * 2.0
        rows.append((real_s, screen_px, ink, dot_d))
        print(R("%.2f" % real_s, 6) + " | "
              + R("%.1f" % effective_font_px(real_s), 6) + " "
              + R(px, 6) + " " + R("%.2f" % screen_px, 10) + " | "
              + R("%.2f" % ink, 13) + " " + R("%.2f" % ink_t, 13) + " | "
              + R("%.2f" % dot_d, 10))

    print("-" * W)
    bad = []
    for i in range(1, len(rows)):
        if rows[i][1] < rows[i - 1][1] - 1e-6:
            bad.append((rows[i - 1][0], rows[i - 1][1], rows[i][0], rows[i][1]))
    print("『放大字号反而变小』的反向台阶: " + str(len(bad)) + " 处")
    for s0, f0, s1, f1 in bad:
        print("    scale %.2f (%.2fpx)  ->  %.2f (%.2fpx)   小了 %.2fpx (%.1f%%)"
              % (s0, f0, s1, f1, f0 - f1, 100.0 * (f0 - f1) / f0))
    lo = min(r[1] for r in rows)
    hi = max(r[1] for r in rows)
    print("全程屏幕字号: %.2f -> %.2f px   （scale 0.08 -> 8.0，放大约 %.0f 倍，"
          "字号变大 %.0f%%）" % (lo, hi, rows[-1][0] / rows[0][0],
                                 100.0 * (hi - lo) / lo))
    print("圆点直径全程恒为 %.2f px（圆点仍是屏幕恒定尺寸）" % rows[0][3])
    print("=" * W)


if __name__ == "__main__":
    main()
