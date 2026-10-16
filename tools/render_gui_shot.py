"""
tools/render_gui_shot.py
================================
离屏启动主窗口，截图保存，用于验证 GUI 真实渲染效果。

用法：
    python tools/render_gui_shot.py [输出路径] [缩放级别]
"""

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_ROOT))

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtCore import QTimer                    # noqa: E402
from PySide6.QtGui import QFont                      # noqa: E402


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (SRC_ROOT / "gui_shot.png")
    zoom = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0

    app = QApplication(sys.argv)
    _f = QFont("Microsoft YaHei", 10)
    _f.setBold(True)
    app.setFont(_f)

    from ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1600, 950)
    w.show()

    def shoot():
        if zoom > 0:
            w.map_view.resetTransform()
            w.map_view.scale(zoom, zoom)
            w.map_view._scale = zoom
            w.map_view._apply_line_width()
            w.map_view._apply_station_scale_all()
        app.processEvents()
        pm = w.grab()
        pm.save(str(out))
        print(f"[OK] 截图已保存: {out}  ({pm.width()}x{pm.height()})")
        app.quit()

    QTimer.singleShot(1200, shoot)
    app.exec()


if __name__ == "__main__":
    main()
