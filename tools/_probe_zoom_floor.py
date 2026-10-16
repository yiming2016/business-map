# -*- coding: utf-8 -*-
"""
只读诊断（v2.6.51）：把"最小档"抬到用户指定的那一档之前，先量清楚底数。

用户要求：滑块最左端 = 1.00×，且**不允许出现比 1 小的数**；
          同时"1 倍"要落在他给的那一档上（缩放 2.3 / 字体 4.5，都是**屏幕显示值**）。
换算：显示值 = 内部真实值 ÷ 基准，现在基准 = 最小档（缩放 0.05 / 字体 0.4）
      ⇒ 2.3 档 = 内部 0.115，4.5 档 = 内部 1.8。

要量的三件事（决定"抬下限"会不会把图锁死）：
  ① fit_map() 之后程序实际停在哪个 scale（全图正好铺满视口时的倍率）；
  ② 代码里写死的 MIN_VIEW_SCALE；
  ③ 面板 zmin / zmax、fmin / fmax。
★ 若 ① < 0.115 ⇒ 把 0.115 设成下限会让"适配全图"被卡住（用户上次骂的"锁死滑动条"）。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="zfloor_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402
from ui.map_view import MIN_VIEW_SCALE                              # noqa: E402


def pump(n=6):
    for _ in range(n):
        QTest.qWait(12)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    for w, h in ((1480, 900), (874, 833)):
        win = MainWindow()
        win.resize(w, h)
        win.show()
        pump(10)
        view = win.map_view
        view.fit_map()
        pump(10)
        sp = getattr(view, "scale_panel", None)
        print(f"\n===== 视口 {w}x{h} =====")
        print(f"  fit_map() 之后 scale      = {view._scale:.4f}")
        print(f"  代码下限 MIN_VIEW_SCALE   = {MIN_VIEW_SCALE}")
        if sp:
            print(f"  面板 zmin / zmax          = {sp.zmin} / {sp.zmax}")
            print(f"  面板 fmin / fmax          = {sp.fmin} / {sp.fmax}")
            print(f"  当前显示 缩放 / 字体      = {sp.lab_zoom.text()} / {sp.lab_font.text()}")
            print(f"  2.3 档 = 内部 {2.3 * sp.zmin:.4f}   4.5 档 = 内部 {4.5 * sp.fmin:.4f}")
            print(f"  若下限抬到 2.3 档：最右显示 {sp.zmax / (2.3 * sp.zmin):.2f}×")
            print(f"  若下限抬到 4.5 档：最右显示 {sp.fmax / (4.5 * sp.fmin):.2f}×")
        win.close()
        pump(4)
    print("\n[DONE] 只读，未改任何文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
