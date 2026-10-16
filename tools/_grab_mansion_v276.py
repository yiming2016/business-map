# -*- coding: utf-8 -*-
"""v2.6.76 特写：后海三图标（红袋+红楼+红宅）+ 站名。"""
import os
import sys

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QPointF, QPoint  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
from ui.main_window import MainWindow  # noqa: E402

win = MainWindow()
win.show()
for _ in range(10):
    app.processEvents()
mv = win.map_view
it = mv.station_items["后海"]
mv.centerOn(QPointF(it.x(), it.y()))
for _ in range(30):
    app.processEvents()
sp = it.label.mapToScene(QPointF(0, 0))
tl = mv.viewport().mapTo(win, mv.mapFromScene(sp))
g = win.grab()
dpr = win.devicePixelRatioF()
x0 = int(max(0, (tl.x() - 160) * dpr))
y0 = int(max(0, (tl.y() - 60) * dpr))
w = int(560 * dpr)
h = int(220 * dpr)
g.copy(x0, y0, min(w, g.width() - x0), min(h, g.height() - y0)).save(
    r"C:/software/subway/源码/_probe_mansion_houhai.png")
win.close()
print("saved")
