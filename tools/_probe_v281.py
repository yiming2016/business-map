# -*- coding: utf-8 -*-
"""v2.6.81 探针：点站点圆点 = 选中该站（修"必须点文字右侧才能选中"）。

T1  合成鼠标按下/松开在圆点上 → _focus_station_id 变 + station_clicked 发射
T2  同一站位再点一次空白处 → clear_selection（回归，不碰旧逻辑）
T3  点站名文字（label 命中路径）→ 依旧选中（旧路径没被破坏）
全程不拖动，不写数据。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["METROEDITOR_NO_ACTIVATE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPointF, QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from ui.main_window import MainWindow

win = MainWindow()
win.resize(1480, 900)
win.show()
for _ in range(10):
    app.processEvents()

CLICKED = []
win.map_view.station_clicked.connect(lambda sid: CLICKED.append(sid))


def _click_view(view_pos):
    gpos = win.map_view.viewport().mapToGlobal(view_pos)
    for t, b in ((QEvent.MouseButtonPress, Qt.LeftButton),
                 (QEvent.MouseButtonRelease, Qt.LeftButton)):
        ev = QMouseEvent(t, QPointF(view_pos), QPointF(gpos), b, Qt.NoButton,
                         Qt.NoModifier)
        app.sendEvent(win.map_view.viewport(), ev)
        app.processEvents()


def _dot_viewpos(sid):
    it = win.map_view.station_items[sid]
    sp = it.mapToScene(QPointF(0, 0))          # 圆点中心（场景坐标）
    return win.map_view.mapFromScene(sp)       # 视口坐标


# ---------- T1：点圆点 = 选中 ----------
sid = "莲塘"
win.map_view.zoom_to_station(sid)
for _ in range(8):
    app.processEvents()
vp = _dot_viewpos(sid)
print(f"[T1] {sid} 圆点视口坐标 = {vp.x()},{vp.y()}")
assert win.map_view.station_at(win.map_view.mapToScene(vp)) is not None, \
    "T1 前置失败：圆点中心没被 station_at 命中"
_click_view(vp)
assert win.map_view._focus_station_id == sid, \
    f"T1 失败：focus={win.map_view._focus_station_id!r}"
assert CLICKED and CLICKED[-1] == sid, f"T1 失败：station_clicked={CLICKED}"
assert win.info_panel.title.text() == sid or win.info_panel._current_station_id == sid, \
    f"T1 失败：信息面板没跟上（{win.info_panel._current_station_id!r}）"
print("[T1] 点圆点 → 选中 + station_clicked + 信息面板 OK")

# ---------- T2：空白处单击 = 取消选中（回归） ----------
dot = _dot_viewpos(sid)
blank = dot + win.map_view.viewport().rect().topLeft()   # 挪到别处
for _dx, _dy in ((180, 160), (220, 200), (-200, 180), (160, -200), (260, 260)):
    cand = blank + type(dot)(_dx, _dy)
    cand = type(dot)(max(8, min(cand.x(), win.map_view.viewport().width() - 8)),
                     max(8, min(cand.y(), win.map_view.viewport().height() - 8)))
    if win.map_view.station_at(win.map_view.mapToScene(cand)) is None:
        blank = cand
        break
assert win.map_view.station_at(win.map_view.mapToScene(blank)) is None, \
    "T2 前置失败：找不到空白点"
CLICKED.clear()
_click_view(blank)
assert win.map_view._focus_station_id == "", \
    f"T2 失败：focus={win.map_view._focus_station_id!r}"
print("[T2] 点空白 → 取消选中 OK")

# ---------- T3：点站名文字 = 选中（旧路径回归） ----------
win.map_view.zoom_to_station(sid)
for _ in range(8):
    app.processEvents()
it = win.map_view.station_items[sid]
lr = it.label_scene_rect()
vp3 = win.map_view.mapFromScene(lr.center())
CLICKED.clear()
_click_view(vp3)
assert win.map_view._focus_station_id == sid and CLICKED, \
    f"T3 失败：focus={win.map_view._focus_station_id!r} clicked={CLICKED}"
print("[T3] 点站名文字 → 选中 OK（旧路径未破坏）")

win.blockSignals(True)
win.close()
print("ALL PASS")
