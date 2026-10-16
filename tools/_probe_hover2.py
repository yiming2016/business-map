# -*- coding: utf-8 -*-
"""临时探针：找一个能在**本环境**里双向驱动场景 hover 的方式（进 + 出）。"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="probehover_"))
for _n in ("stations.json", "lines.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import Qt, QPointF, QEvent       # noqa: E402
from PySide6.QtWidgets import (QApplication,         # noqa: E402
                               QGraphicsSceneHoverEvent,
                               QGraphicsSceneMouseEvent)
from ui.main_window import MainWindow                # noqa: E402

_KEEP: list = []


def pump(n=20):
    for _ in range(n):
        QApplication.processEvents()


app = QApplication(sys.argv)
win = MainWindow()
win.resize(1480, 900)
win.show()
pump(40)
_KEEP.append(win)
mv = win.map_view
mv._apply_zoom_transform(1.0 / max(mv._scale, 1e-9), mv.viewport().rect().center())
mv._sync_zoom_state()
mv._apply_station_scale_all()
mv._apply_line_width()
pump(20)

scene = mv.scene_
lids = sorted(mv.line_items.keys())
it = mv.line_items[lids[0]]
path = it.path()
print("[diag] _scale =", mv._scale)
print("[diag] it._view_scale =", it._view_scale)
print("[diag] it.pos() =", it.pos(), " it.transform =", it.transform())
print("[diag] parent =", it.parentItem())
print("[diag] path.boundingRect =", path.boundingRect())
print("[diag] it.sceneBoundingRect =", it.sceneBoundingRect())
print("[diag] isVisible =", it.isVisible(), " elementCount =", path.elementCount())
print("[diag] shape().boundingRect =", it.shape().boundingRect())
boxes = [s.sceneBoundingRect() for s in mv.station_items.values()]
on = None
for i in range(path.elementCount()):
    e = path.elementAt(i)
    p = QPointF(e.x, e.y)
    if not any(b.contains(p) for b in boxes):
        on = p
        break
print("线路", lids[0], "取样点", on, "shape含=", it.shape().contains(on))
print("[diag] scene.items 数 =", len(scene.items(on)))

print("scene 有 sendEvent =", hasattr(scene, "sendEvent"))
print("scene 有 sendHoverEvent =", hasattr(scene, "sendHoverEvent"))


def hover_ev(t, pos, last):
    ev = QGraphicsSceneHoverEvent(t)
    ev.setScenePos(pos)
    ev.setPos(pos)
    ev.setLastScenePos(last)
    ev.setLastPos(last)
    ev.setModifiers(Qt.NoModifier)
    return ev


far = QPointF(on.x() + 400.0, on.y() + 400.0)

# ---------- 方式 1：scene.sendEvent ----------
print("\n--- 方式 1: scene.sendEvent(item, hover) ---")
try:
    scene.sendEvent(it, hover_ev(QEvent.GraphicsSceneHoverEnter, on, far))
    pump(10)
    print("  enter 后 _hover =", it._hover)
    scene.sendEvent(it, hover_ev(QEvent.GraphicsSceneHoverLeave, far, on))
    pump(10)
    print("  leave 后 _hover =", it._hover)
except Exception as e:
    print("  抛异常:", type(e).__name__, e)

# ---------- 方式 2：直接调 item 的 hover 处理函数 ----------
print("\n--- 方式 2: 直接 item.hoverEnterEvent ---")
it._hover = False
mv.highlight_line("")
pump(6)
try:
    it.hoverEnterEvent(hover_ev(QEvent.GraphicsSceneHoverEnter, on, far))
    pump(10)
    print("  enter 后 _hover =", it._hover, " 线宽", it.screen_width)
    it.hoverLeaveEvent(hover_ev(QEvent.GraphicsSceneHoverLeave, far, on))
    pump(10)
    print("  leave 后 _hover =", it._hover, " 线宽", it.screen_width)
except Exception as e:
    print("  抛异常:", type(e).__name__, e)

# ---------- 方式 3：scene 里 itemAt / items 能不能挑出线路 ----------
print("\n--- 方式 3: scene.items(pos) ---")
lst = scene.items(on)
print("  该点下 top3 =", [type(x).__name__ for x in lst[:3]])
print("  线路在列表里 =", it in lst)
print("  topmost 接 hover =", lst[0].acceptHoverEvents() if lst else None)

# ---------- 方式 4：连发两次 scene mouse move，看 leave ----------
print("\n--- 方式 4: 连发 QGraphicsSceneMouseEvent ---")
mv.highlight_line("")
pump(6)


def mm(cur, prev):
    ev = QGraphicsSceneMouseEvent(QEvent.GraphicsSceneMouseMove)
    ev.setScenePos(cur)
    ev.setPos(cur)
    ev.setLastScenePos(prev)
    ev.setLastPos(prev)
    ev.setButton(Qt.NoButton)
    ev.setButtons(Qt.NoButton)
    ev.setModifiers(Qt.NoModifier)
    scene.mouseMoveEvent(ev)
    pump(16)


mm(on, far)
print("  ① 移到线路上   _hover =", it._hover, " 线宽", it.screen_width)
mm(far, on)
print("  ② 移到远处空地 _hover =", it._hover, " 线宽", it.screen_width)
mm(on, far)
print("  ③ 再移回线路   _hover =", it._hover, " 线宽", it.screen_width)

print("\nprobe 结束")
