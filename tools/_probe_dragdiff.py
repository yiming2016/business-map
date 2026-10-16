# -*- coding: utf-8 -*-
"""定位 B4「拖动后 data 与图元不一致」的根因：逐步打印坐标。"""
import os, sys, tempfile, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

import core.data_manager as CDM
_TMP = Path(tempfile.mkdtemp(prefix="dragdiff_"))
for _n in ("stations.json", "lines.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"

from PySide6.QtCore import QPointF, QEvent, Qt
from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent
app = QApplication(sys.argv)
from ui.main_window import MainWindow

w = MainWindow(); w.resize(1480, 900); w.show()
for _ in range(6): app.processEvents()
w._apply_lock_states(False, False)     # 解锁
for _ in range(3): app.processEvents()

sid = "会展中心"
it = w.map_view.station_items[sid]


def _ev(item, typ, scene_pos, btn=Qt.LeftButton):
    e = QGraphicsSceneMouseEvent(typ)
    e.setButton(btn)
    e.setButtons(btn)
    e.setScenePos(QPointF(scene_pos))
    e.setPos(item.mapFromScene(QPointF(scene_pos)))
    e.setButtonDownScenePos(btn, QPointF(scene_pos))
    e.setButtonDownPos(btn, item.mapFromScene(QPointF(scene_pos)))
    return e


# ---- A 段：先用 QTest 走完整 view 事件链单击一次（复刻脚本序列）----
from PySide6.QtTest import QTest
vp = w.map_view.mapFromScene(QPointF(it.pos()))
QTest.mouseClick(w.map_view.viewport(), Qt.LeftButton, Qt.NoModifier, vp)
for _ in range(3):
    app.processEvents()
print("A段单击后: dm.x =", (w.dm.get_station(sid) or {}).get("x"),
      " item.data.x =", it.data.get("x"), " pos.x =", it.pos().x())
print("A段后 item.data is dm dict?", it.data is (w.dm.get_station(sid)))
print("A段后 _press_dot =", w.map_view._press_dot, " _press_dot_pos =", w.map_view._press_dot_pos)

p0 = QPointF(it.pos())
print("起始 pos =", p0, " data =", it.data.get("x"), it.data.get("y"))
print("data is dm's dict? ", it.data is (w.dm.get_station(sid)))

it.mousePressEvent(_ev(it, QEvent.Type.GraphicsSceneMousePress, p0))
print("press 后 _press_pos =", getattr(it, "_press_pos", None),
      " _drag_last_pos =", getattr(it, "_drag_last_pos", None))

target = QPointF(p0.x() + 20.0, p0.y())
it.setPos(target)
print("setPos#1 后 pos =", it.pos(), "（target =", target, "）")

it.mouseMoveEvent(_ev(it, QEvent.Type.GraphicsSceneMouseMove, target))
print("move 后 pos =", it.pos(), " data =", it.data.get("x"), it.data.get("y"))

it.setPos(target)
print("setPos#2 后 pos =", it.pos())

it.mouseReleaseEvent(_ev(it, QEvent.Type.GraphicsSceneMouseRelease, target))
print("release 后 pos =", it.pos(), " data =", it.data.get("x"), it.data.get("y"))

rec = w.dm.get_station(sid) or {}
print("dm 记录 x/y =", rec.get("x"), rec.get("y"))
print("差异 =", abs((rec.get("x") or 0) - it.pos().x()), "(x)")
