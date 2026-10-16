# -*- coding: utf-8 -*-
"""探针：**缩放的同时拖动**（按住左键平移期间还在滚轮缩放）到底发生了什么？

用户报告：「缩放同时进行移动会有卡顿的现象」。

这个探针不复用任何假设，只回答四个问题（都在**真实主窗口 874×829 视口**上量）：

  Q1 事件时序：这条手势里，缩放动画被打断（abort）了几次？
               每次打断要多久？（打断会做一次"全场景同步重绘"，很贵）
  Q2 卡顿有多大：主线程最长被堵多久？（4ms 心跳定时器测最大间隔 = 掉帧）
                 哪一段最慢？（合成帧 / 打断 / 收尾）
  Q3 拖动去哪了：拖了多少像素，滚动条有没有真的跟着走？
                 ★ 重点：动画期间拖动会不会被"收尾对齐"覆盖掉（= 拖了白拖）
  Q4 对照：单独滚轮（不拖）vs 单独拖动 vs 边滚边拖 —— 三者的最大卡顿对比。

运行：
    C:\\Users\\29773\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe tools/_probe_zoom_pan.py
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

WHEEL_DELTA = -120          # 负 = 缩小（与"缩放+移动"里常见的缩小方向一致）


# ----------------------------------------------------------------------
# 主线程卡顿监测（4ms 心跳，量最大间隔）
# ----------------------------------------------------------------------
class StallWatch:
    """4ms 心跳定时器：主线程被堵住时，两次心跳之间的间隔会出现大洞。

    这是**只有真机才有意义**的指标 —— 离线 render() 计时测不出事件循环里的堵。
    """

    def __init__(self, app):
        self.app = app
        self.gaps: list = []
        self._last = 0.0
        self.timer = QTimer()
        self.timer.setInterval(4)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        now = time.perf_counter()
        if self._last:
            self.gaps.append(1000.0 * (now - self._last))
        self._last = now

    def start(self):
        self.gaps = []
        self._last = 0.0
        self.timer.start()

    def stop(self):
        self.timer.stop()
        if not self.gaps:
            return 0.0, 0.0
        # 心跳间隔里本身含 4ms 周期，减掉才是"多堵的时间"
        worst = max(self.gaps)
        return worst, max(0.0, worst - 4.0)


class Counters:
    """给 MapView 的几个关键方法套一层计时马甲。"""

    def __init__(self, mv):
        self.mv = mv
        self.data: dict = {}

    def wrap(self, name: str):
        orig = getattr(self.mv, name)

        def wrapper(*a, **kw):
            t0 = time.perf_counter()
            try:
                return orig(*a, **kw)
            finally:
                d = self.data.setdefault(name, {"n": 0, "ms": 0.0, "worst": 0.0})
                ms = 1000.0 * (time.perf_counter() - t0)
                d["n"] += 1
                d["ms"] += ms
                d["worst"] = max(d["worst"], ms)

        setattr(self.mv, name, wrapper)

    def reset(self):
        self.data = {}

    def get(self, name: str):
        return self.data.get(name, {"n": 0, "ms": 0.0, "worst": 0.0})


# ----------------------------------------------------------------------
# 事件构造（发到 viewport，就是真实分发路径）
# ----------------------------------------------------------------------
def send_press(vp, pos: QPoint):
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(pos),
                     vp.mapToGlobal(pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(vp, ev)


def send_move(vp, pos: QPoint):
    ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(pos),
                     vp.mapToGlobal(pos), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(vp, ev)


def send_release(vp, pos: QPoint):
    ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(pos),
                     vp.mapToGlobal(pos), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(vp, ev)


def send_wheel(vp, pos: QPoint, delta: int = WHEEL_DELTA):
    ev = QWheelEvent(QPointF(pos), vp.mapToGlobal(pos), QPoint(0, 0), QPoint(0, delta),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(vp, ev)


def find_empty_point(mv) -> QPoint:
    """在视口里找一个"底下没有站点"的位置（才可能触发平移）。"""
    vp = mv.viewport()
    for y in range(60, vp.height() - 40, 37):
        for x in range(60, vp.width() - 40, 37):
            if mv.station_at(mv.mapToScene(QPoint(x, y))) is None:
                return QPoint(x, y)
    return QPoint(vp.width() // 2, vp.height() // 2)


def pump(ms: int, watch: StallWatch = None) -> None:
    """跑 ms 毫秒真实事件循环。"""
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.0005)


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    win.activateWindow()

    mv = win.map_view
    vp = mv.viewport()
    pump(400)
    print(f"主窗口 {win.width()}x{win.height()}   地图视口 {vp.width()}x{vp.height()}   "
          f"scale={mv._scale:.3f}  站点 {len(mv.station_items)}")
    print()

    ctr = Counters(mv)
    for name in ("_compose_frame", "_abort_zoom_snap", "_end_zoom_snap",
                 "_apply_station_scale_all", "_update_label_visibility"):
        ctr.wrap(name)

    watch = StallWatch(app)

    # ================================================================
    # 场景 1：单独滚轮缩小（对照基线）
    # ================================================================
    def scenario_wheel_only(n=8):
        p = QPoint(vp.width() // 2, vp.height() // 2)
        return p, None, None

    # ================================================================
    # 场景 2：单独拖动平移（对照基线）
    # ================================================================
    # ================================================================
    # 场景 3：★ 边滚轮缩放、边按住左键拖动（用户报告的"缩放同时移动"）
    # ================================================================
    def run(name, kind, moves=14, step=9, delta=WHEEL_DELTA, wheel_every=1):
        mv._sync_zoom_state()
        pump(300)
        start = find_empty_point(mv)
        h0 = mv.horizontalScrollBar().value()
        v0 = mv.verticalScrollBar().value()
        ctr.reset()
        watch.start()

        pos = QPoint(start)
        drag_x = drag_y = 0
        if kind in ("pan", "both"):
            send_press(vp, pos)
        for i in range(moves):
            if kind in ("pan", "both"):
                pos = QPoint(pos.x() + step, pos.y() + step)
                drag_x += step
                drag_y += step
                send_move(vp, pos)
            if kind in ("wheel", "both"):
                if i % wheel_every == 0:
                    send_wheel(vp, pos if kind == "both" else QPoint(vp.width() // 2,
                                                                    vp.height() // 2), delta)
            pump(12, watch)
        if kind in ("pan", "both"):
            send_release(vp, pos)
        pump(450, watch)          # 等缩放收尾（160ms 定时器 + 重绘）
        worst, extra = watch.stop()

        h1 = mv.horizontalScrollBar().value()
        v1 = mv.verticalScrollBar().value()
        moved = (h1 - h0) + (v1 - v0)          # 滚动条实际变化（缩小时 h/v 也会变）
        print(f"── {name} ──")
        print(f"   最大掉帧 {worst:.1f}ms（扣除心跳周期 {extra:.1f}ms）  "
              f"scale {mv._scale:.3f}")
        if kind in ("pan", "both"):
            print(f"   拖动 {drag_x}px → 期望滚动条变 {drag_x}px；"
                  f"实际 h {h0}→{h1}（{h1-h0:+d}）, v {v0}→{v1}（{v1-v0:+d}）")
        for k in ("_compose_frame", "_abort_zoom_snap", "_end_zoom_snap",
                  "_apply_station_scale_all", "_update_label_visibility"):
            d = ctr.get(k)
            if d["n"]:
                print(f"   {k:26s} 调用 {d['n']:3d} 次  合计 {d['ms']:7.1f}ms  "
                      f"最慢 {d['worst']:6.1f}ms")
        print()
        return worst

    print("=" * 70)
    print("对照实验")
    print("=" * 70)
    run("场景1 只滚轮（缩小）", "wheel", moves=14)
    run("场景2 只拖动（不缩放）", "pan", moves=14)
    run("场景3 边滚轮边拖动 ★", "both", moves=14)

    print("=" * 70)
    print("细节：拖动到一半才开始滚轮（更接近真人：先拖一下再滚）")
    print("=" * 70)
    run("场景4 先拖 6 步、后 8 步边拖边滚", "both", moves=14)

    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
