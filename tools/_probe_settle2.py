# -*- coding: utf-8 -*-
"""探针：松手后每一段"阻塞"是谁干的？—— 归因时间轴。

为什么需要它：掉帧时间轴只告诉你"何时卡了 15ms"，不告诉你"谁卡的"。
本探针给所有可疑方法套计时，凡是单次 >5ms 就记一条
        (相对松手的时刻, 方法名, 耗时)
最后按时间排序打印 —— 每一段阻塞都直接点名，不用再推理。

覆盖：paintEvent / _reveal_tick / _sprite_sweep_tick / _compose_frame /
      _apply_station_scale_all / _begin_reveal / _end_zoom_snap /
      _apply_zoom_transform / _update_label_visibility / _apply_view_scale(单站)

运行：python tools/_probe_settle2.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

T0 = 0.0
LOG: list = []          # (t_rel, name, ms)
WRAPPED = []


def rel():
    return time.perf_counter() - T0


def watch(obj, name, threshold_ms=5.0):
    orig = getattr(obj, name)

    def wrapper(*a, **kw):
        t0 = time.perf_counter()
        try:
            return orig(*a, **kw)
        finally:
            ms = 1000.0 * (time.perf_counter() - t0)
            if ms >= threshold_ms:
                LOG.append((rel(), name, ms))
    setattr(obj, name, wrapper)
    WRAPPED.append(name)


def pump(ms):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.0005)


def send(vp, kind, pos, delta=0):
    if kind == "press":
        ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(pos),
                         vp.mapToGlobal(pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    elif kind == "move":
        ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(pos),
                         vp.mapToGlobal(pos), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    elif kind == "release":
        ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(pos),
                         vp.mapToGlobal(pos), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    else:
        ev = QWheelEvent(QPointF(pos), vp.mapToGlobal(pos), QPoint(0, 0),
                         QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
    QApplication.sendEvent(vp, ev)


def main() -> int:
    global T0
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    win.activateWindow()
    pump(500)

    mv = win.map_view
    vp = mv.viewport()
    print(f"视口 {vp.width()}x{vp.height()}  scale={mv._scale:.4f}  站点 {len(mv.station_items)}")

    for n in ("paintEvent", "_reveal_tick", "_sprite_sweep_tick", "_compose_frame",
              "_apply_station_scale_all", "_begin_reveal", "_end_zoom_snap",
              "_apply_zoom_transform", "_update_label_visibility"):
        watch(mv, n)
    items = list(mv.station_items.values())
    orig_avs = type(items[0]).apply_view_scale

    def avs(self, s):
        t0 = time.perf_counter()
        try:
            return orig_avs(self, s)
        finally:
            ms = 1000.0 * (time.perf_counter() - t0)
            if ms >= 5.0:
                LOG.append((rel(), "apply_view_scale(单站)", ms))
    type(items[0]).apply_view_scale = avs

    # ---- 手势：滚轮放大 + 边滚边拖 ----
    p0 = QPoint(80, 80)
    send(vp, "press", p0)
    pos = QPoint(p0)
    for i in range(6):
        pos = QPoint(pos.x() + 9, pos.y() + 9)
        send(vp, "move", pos)
        send(vp, "wheel", pos, 120)
        pump(12)
    for i in range(8):
        pos = QPoint(pos.x() + 9, pos.y() + 9)
        send(vp, "move", pos)
        pump(10)
    send(vp, "release", pos)

    LOG.clear()                      # 只关心松手之后
    T0 = time.perf_counter()
    end = T0 + 1.5
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.002)

    print(f"\n松手后 >5ms 的阻塞（共 {len(LOG)} 条），按时间排序：")
    print(f"{'时刻':>8s}  {'耗时':>7s}  谁")
    print("-" * 60)
    for t, name, ms in sorted(LOG):
        print(f"{1000*t:+7.0f}ms  {ms:6.1f}ms  {name}")

    tot = sum(ms for _, _, ms in LOG)
    print("-" * 60)
    print(f"合计阻塞 {tot:.1f}ms（1.5s 窗口）")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
