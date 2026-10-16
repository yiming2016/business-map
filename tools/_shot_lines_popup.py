# -*- coding: utf-8 -*-
"""给"所属线路"下拉面板截图，确认展开后是**一行 3 个**。

用法：
    python tools/_shot_lines_popup.py            # 默认站"机场东"
    python tools/_shot_lines_popup.py 车公庙
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtCore import QTimer, QPoint           # noqa: E402

from ui.edit_dialog import EditDialog               # noqa: E402

sid = sys.argv[1] if len(sys.argv) > 1 else "机场东"
out_dir = SRC / "logs"
out_dir.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
dlg = EditDialog(station_id=sid)
dlg.show()

ls = dlg._widgets["lines"]


def shoot():
    dlg.raise_()
    app.processEvents()
    # 展开下拉面板
    ls._toggle_popup()
    app.processEvents()
    pop = ls._popup
    pop.repaint()
    app.processEvents()

    p1 = out_dir / "_dialog_with_popup.png"
    p2 = out_dir / "_lines_popup.png"
    dlg.grab().save(str(p1))

    # 面板是 Qt.Popup 顶层窗口，dlg.grab() 抓不到，只能抓屏幕。
    # 注意：高 DPI 下 QScreen.grabWindow 的 x/y/w/h 是「逻辑像素」，
    # 返回的 QPixmap 带 devicePixelRatio，裁剪时坐标要乘 DPR。
    scr = QApplication.primaryScreen()
    full = scr.grabWindow(0)
    dpr = full.devicePixelRatio() or 1.0
    tl = pop.mapToGlobal(QPoint(0, 0))
    pad = 40
    pm = full.copy(int((tl.x() - pad) * dpr), int((tl.y() - pad) * dpr),
                   int((pop.width() + 2 * pad) * dpr),
                   int((pop.height() + 2 * pad) * dpr))
    pm.save(str(p2))

    rows = pop.layout().rowCount()
    cols = pop.layout().columnCount()
    n = len(pop.checkboxes())
    print(f"[OK] 弹窗+面板: {p1}")
    print(f"[OK] 面板单独: {p2}  ({pm.width()}x{pm.height()} dpr={dpr})")
    print(f"候选项 {n} 个 -> 网格 {rows} 行 x {cols} 列")

    pop.hide()
    app.quit()


QTimer.singleShot(700, shoot)
sys.exit(app.exec())
