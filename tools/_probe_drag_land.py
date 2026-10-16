# -*- coding: utf-8 -*-
"""探针：**边缩放边拖动里的"拖动"到底有没有落地？**（决定性判据）

为什么不用"滚动条变化量"做判据：
    滚动条值 = f(缩放, 场景框, 视口)，缩放本身就是滚动条的大头，
    把"期望 126px"当基准会把缩放的贡献算到拖动头上 → 结论不可信。

本探针用的判据是**平移手势的本征不变量**：
    缩放锚点固定在按下点 p0，绕 p0 缩放时"p0 下的那个场景点"恒定不动；
    于是若拖动真的落地，手势结束后
        mapToScene(p0 + d)  ==  手势开始时的 mapToScene(p0)
    成立（屏幕上就是"内容跟着手指走"）。
    若拖动被丢掉，左式会偏离 asc 达 d / scale 个场景单位 —— 差之千里，一眼可判。

三个观测：
    ① 拖动结束时 _snap_pan（= 手势累计平移，屏幕像素）——有没有抓到？
    ② 收尾后 mapToScene(p0+d) 与 asc 的偏差（场景单位）+ 换算成屏幕像素的偏差
    ③ 收尾耗时（顺带看冻结）

运行：
    python tools/_probe_drag_land.py
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


# ----------------------------------------------------------------------
# 事件构造
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


def send_wheel(vp, pos: QPoint, delta: int):
    ev = QWheelEvent(QPointF(pos), vp.mapToGlobal(pos), QPoint(0, 0), QPoint(0, delta),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(vp, ev)


def find_empty_point(mv) -> QPoint:
    vp = mv.viewport()
    for y in range(80, vp.height() - 90, 29):
        for x in range(80, vp.width() - 90, 29):
            if mv.station_at(mv.mapToScene(QPoint(x, y))) is None:
                return QPoint(x, y)
    return QPoint(vp.width() // 2, vp.height() // 2)


def pump(ms: int) -> None:
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.0005)


# ----------------------------------------------------------------------
# 主线程卡顿
# ----------------------------------------------------------------------
class StallWatch:
    """4ms 心跳：记录每次"掉帧"的时间点与时长，画出一条时间轴。

    ★ 只有时间轴能回答"用户在什么时候感觉到什么"：
      松手后 0.16s 出现的那次长停顿 = 收尾落地；此后一串小停顿 = 分条揭开。
    """

    def __init__(self):
        self.gaps: list = []
        self._last = 0.0
        self._t0 = 0.0
        self.events: list = []          # (相对松手的秒数, 间隔ms)
        self.timer = QTimer()
        self.timer.setInterval(4)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        now = time.perf_counter()
        if self._last:
            gap = 1000.0 * (now - self._last)
            self.gaps.append(gap)
            if gap > 12.0:
                self.events.append((now - self._t0, gap))
        self._last = now

    def start(self):
        self.gaps = []
        self.events = []
        self._last = 0.0
        self._t0 = time.perf_counter()
        self.timer.start()

    def mark(self):
        """把时间轴的零点挪到此刻（一般放在"松手"那一行）。"""
        self._t0 = time.perf_counter()

    def stop(self):
        self.timer.stop()
        if not self.gaps:
            return 0.0
        return max(self.gaps)

    def timeline(self, rel_to_mark: float = 0.0):
        out = []
        for t, g in self.events[:24]:
            out.append(f"{(t - rel_to_mark) * 1000:+6.0f}ms:{g:5.1f}")
        return "  ".join(out)


def run_case(win, title: str, *, zoom_in: int, drag_px: int, drag_first: bool):
    """一个场景：滚轮启动缩放动画 → 动画进行中按住拖动 → 松手 → 等收尾。"""
    mv = win.map_view
    vp = mv.viewport()

    mv._sync_zoom_state()
    pump(300)

    p0 = find_empty_point(mv)
    asc0 = mv.mapToScene(p0)                    # 手势开始：p0 下的场景点（不变量基准）
    s_before = mv._scale
    watch = StallWatch()

    print(f"── {title} ──")
    print(f"   scale(手势前) {s_before:.4f}   p0={p0.x()},{p0.y()}   "
          f"asc0=({asc0.x():.2f},{asc0.y():.2f})")
    print(f"   滚动条 h[{mv.horizontalScrollBar().minimum()},"
          f"{mv.horizontalScrollBar().maximum()}] = {mv.horizontalScrollBar().value()}   "
          f"v[{mv.verticalScrollBar().minimum()},{mv.verticalScrollBar().maximum()}] = "
          f"{mv.verticalScrollBar().value()}")

    watch.start()
    if drag_first:
        # 先拖 2 步（把"按住"这个状态建立起来），再开始滚轮
        send_press(vp, p0)
        for _ in range(2):
            p0 = QPoint(p0.x() + 3, p0.y() + 3)
            send_move(vp, p0)
            pump(10)

    for _ in range(zoom_in):
        send_wheel(vp, p0, 120)                 # 正 = 放大（内容大于视口，平移才有意义）
        pump(12)

    # ---- 拖动（此后不再滚轮，锚点固定 = p0）----
    pos = QPoint(p0)
    if not drag_first:
        send_press(vp, pos)
    drag = QPoint(0, 0)
    for _ in range(14):
        pos = QPoint(pos.x() + drag_px, pos.y() + drag_px)
        drag += QPoint(drag_px, drag_px)
        send_move(vp, pos)
        pump(10)

    # ① 松手前的 _snap_pan（有没有抓到拖动）
    snap = mv._snap_pan
    snapping = mv._zoom_snap is not None
    send_release(vp, pos)
    watch.mark()                                # 时间轴零点 = 松手时刻
    t_rel = time.perf_counter()
    pump(700)                                   # 等收尾 + 分条揭开走完
    stall = watch.stop()
    t_release_to_settled = time.perf_counter() - t_rel

    # ② 收尾后的不变量检查
    s_after = mv._scale
    asc_now = mv.mapToScene(pos)
    dev_scene = QPointF(asc_now.x() - asc0.x(), asc_now.y() - asc0.y())
    dev_px = (dev_scene.x() * s_after, dev_scene.y() * s_after)

    print(f"   拖动 {drag.x()}px 期间 _snap_pan=({snap.x():.1f},{snap.y():.1f})  "
          f"快照仍在={snapping}")
    print(f"   scale(收尾后) {s_after:.4f}   最大掉帧 {stall:.1f}ms")
    print(f"   不变量：mapToScene(p0+d) - asc0 = ({dev_scene.x():+.1f},{dev_scene.y():+.1f}) 场景单位")
    print(f"           = ({dev_px[0]:+.1f},{dev_px[1]:+.1f}) 屏幕像素"
          f"   （0 = 拖动完全落地；≈{drag.x()} = 拖动被丢弃）")
    verdict = "落地 OK" if max(abs(dev_px[0]), abs(dev_px[1])) < 6 else "★拖动丢了"
    print(f"   判定：{verdict}")
    print(f"   松手后掉帧时间轴（相对松手，只列 >12ms 的）：")
    print(f"     {watch.timeline(rel_to_mark=0.0) or '（无 >12ms 掉帧）'}")
    print()
    return dev_px, stall


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    win.activateWindow()
    pump(400)

    mv = win.map_view
    vp = mv.viewport()
    print(f"主窗口 {win.width()}x{win.height()}   地图视口 {vp.width()}x{vp.height()}   "
          f"初始 scale={mv._scale:.4f}  站点 {len(mv.station_items)}")
    print()

    run_case(win, "对照：只滚轮放大、不拖动", zoom_in=6, drag_px=0, drag_first=False)
    run_case(win, "A 滚轮放大 → 动画中拖动", zoom_in=6, drag_px=9, drag_first=False)
    run_case(win, "B 先按住拖动 → 再边滚边拖", zoom_in=6, drag_px=9, drag_first=True)

    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
