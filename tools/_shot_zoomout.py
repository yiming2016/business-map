# -*- coding: utf-8 -*-
"""探针：按给定"站名挤压"参数截一张地图（真实视口 874x829），用来看画面对不对。

用法：
    python tools/_shot_zoomout.py --scale 0.093 --tol 0.25 --tag t25
    python tools/_shot_zoomout.py --scale min  --tol 0    --tag base

参数：
    --scale  min | fit | 具体数值（默认 min）
    --tol    允许站名互相压掉的面积比例（0 = 一点都不许压）
    --fontmin 站名字号下限（默认沿用代码里的值）
    --dots   1/0  站名是否必须避开别站圆点（1=避开，默认）
    --pad    站名之间的留白（屏幕像素，默认沿用代码里的值）
输出：logs/_zoomshot_<tag>.png
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer                        # noqa: E402
from PySide6.QtGui import QFont                          # noqa: E402
from PySide6.QtWidgets import QApplication               # noqa: E402

import ui.metro_render as MR                             # noqa: E402
import ui.map_view as MV                                 # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="min")
    ap.add_argument("--tol", type=float, default=None)
    ap.add_argument("--fontmin", type=float, default=None)
    ap.add_argument("--dots", type=int, default=None)
    ap.add_argument("--pad", type=float, default=None)
    ap.add_argument("--tag", default="shot")
    a = ap.parse_args()

    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)

    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    mv = win.map_view
    out = ROOT / "logs"

    def pump(n=30):
        for _ in range(n):
            app.processEvents()

    def run():
        pump(40)
        if a.tol is not None:
            MV.LABEL_OVERLAP_TOL = a.tol
        if a.pad is not None:
            MV.LABEL_PAD = MV.LABEL_PAD_TIGHT = a.pad
        if a.fontmin is not None:
            MR.SCREEN_FONT_MIN_PX = a.fontmin
        if a.dots is not None:
            MV.LABEL_AVOID_DOTS = bool(a.dots)

        if a.scale == "min":
            target = mv._min_scale_for_viewport()
        elif a.scale == "fit":
            mv.fit_map()
            target = mv._scale
        else:
            target = float(a.scale)

        if abs(target - mv._scale) > 1e-9:
            mv._apply_zoom_transform(target / max(mv._scale, 1e-9),
                                     mv.viewport().rect().center())
        mv._sync_zoom_state()
        mv._apply_station_scale_all()
        pump(20)
        mv._invalidate_nn()
        mv._update_label_visibility()
        pump(30)

        shown = sum(1 for it in mv.station_items.values() if it._label_on)
        total = len(mv.station_items)
        print(f"scale={mv._scale:.4f} tol={MV.LABEL_OVERLAP_TOL} "
              f"fontmin={MR.SCREEN_FONT_MIN_PX} pad={MV.LABEL_PAD} "
              f"avoid_dots={MV.LABEL_AVOID_DOTS}")
        print(f"显示站名 {shown}/{total} = {shown * 100.0 / total:.1f}%")
        pm = mv.viewport().grab()
        path = out / f"_zoomshot_{a.tag}.png"
        ok = pm.save(str(path))
        print(f"→ {path}  {pm.width()}x{pm.height()}  save={ok}")
        QTimer.singleShot(0, app.quit)

    QTimer.singleShot(300, run)
    app.exec()
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
