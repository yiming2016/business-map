"""
tools/check_labels.py
================================
验证站名防重叠排版：统计各缩放级别下能显示的站名数量 + 测量排版耗时。

用法：
    python tools/check_labels.py
"""

import sys
import time
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_ROOT))

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtCore import QTimer                    # noqa: E402
from PySide6.QtGui import QFont                      # noqa: E402


def main():
    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)

    from ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1600, 950)
    w.show()

    def run():
        mv = w.map_view
        total = len(mv.station_items)
        print(f"站点总数: {total}")
        print()
        print(f"{'缩放':>8} | {'显示站名':>8} | {'占比':>6} | {'排版耗时':>9}")
        print("-" * 46)

        for s in (0.10, 0.12, 0.16, 0.22, 0.30, 0.45, 0.60, 1.00):
            mv.resetTransform()
            mv.scale(s, s)
            mv._scale = s
            t0 = time.perf_counter()
            mv._apply_station_scale_all()
            dt = (time.perf_counter() - t0) * 1000
            shown = sum(1 for it in mv.station_items.values() if it.is_label_visible())
            print(f"{s:>8.2f} | {shown:>8d} | {shown / total * 100:>5.1f}% | {dt:>7.1f}ms")

        # 焦点站优先验证
        mv.fit_map()
        name = "车公庙" if "车公庙" in mv.station_items else list(mv.station_items)[0]
        mv.select_station(name)
        it = mv.station_items[name]
        print()
        print(f"选中「{name}」后该站名可见: {it.is_label_visible()}  方向: {it.label_side()}")

        app.quit()

    QTimer.singleShot(1200, run)
    app.exec()


if __name__ == "__main__":
    main()
