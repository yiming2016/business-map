# -*- coding: utf-8 -*-
"""回归：**缩放的同时拖动**（用户报告"缩放同时进行移动会有卡顿"）。

v2.5.2 的两个真问题（探针实测，非猜测）：
  ① 拖动被整个丢掉：动画期间按左键平移，收尾按"冻结的快照锚点"重设滚动条，
     把刚拖出来的位移覆盖掉 —— 实测"拖了 126px、滚动条变化 +0/+0"，纯粹白拖。
  ② 收尾那一步（落真实变换 + 更新 379 个站点尺寸 + 重排版 = 全场景重绘）
     会落在"刚缩完手还在动"的中间：实测主线程最长堵 **212ms**。

场景 A —— 决定性不变量（锚点固定）
    滚轮全部发在同一个位置 p0，拖动紧随其后（不再滚轮）。
    此时锚点恒为 p0，绕 p0 缩放不改变"p0 下的场景点"，于是拖动落地 ⇔
        mapToScene(p0 + 总拖动) == 手势开始时的 mapToScene(p0)
    拖动被丢掉时左式会差出整整 d 个屏幕像素（不是几个像素的噪声）。

场景 B —— 交错（更接近真人：边滚边拖）
    锚点会随光标重定位（这是设计：缩放原点跟着鼠标走），所以上面那个
    不变量不再适用；这里改为断言"拖动一像素都没丢"（_snap_pan == 总拖动）
    + "拖动期间绝不做收尾" + 两段卡顿预算。
    画面是否与真实渲染对齐，由 _chk_reveal_align.py 用像素比对负责。

运行：python tools/_chk_zoom_pan.py
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

PASS = FAIL = 0
# 标定（都是 874x833 视口、379 站点、4ms 心跳实测）：
#   手势期间（用户真在滚/拖的那一段）：
#       v2.5.2 = 212ms（收尾整个落进手势中间）  →  v2.5.3 = 24~42ms
#       阈值 60ms：比实测留一倍余量，又能抓住"收尾又跑回手势里"的回归。
#   收尾段（松手之后）：
#       v2.5.2 = 212ms  →  v2.5.3 = 43ms（放大）/ 61~66ms（缩小，要重排版）
#       实测波动区间 43~130ms（事件循环批次不同会把"收尾+首条揭开"并成一个洞），
#       所以这条只当粗护栏用：真正要守的是上面那条手势阈值。
GESTURE_STALL_MAX_MS = 60.0
SETTLE_STALL_MAX_MS = 200.0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}   {detail}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}   {detail}")


def pump(ms: float) -> None:
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.0005)


def ev(vp, kind, pos, delta=0):
    p, g = QPointF(pos), vp.mapToGlobal(pos)
    if kind == "press":
        e = QMouseEvent(QEvent.Type.MouseButtonPress, p, g, Qt.LeftButton,
                        Qt.LeftButton, Qt.NoModifier)
    elif kind == "move":
        e = QMouseEvent(QEvent.Type.MouseMove, p, g, Qt.NoButton,
                        Qt.LeftButton, Qt.NoModifier)
    elif kind == "release":
        e = QMouseEvent(QEvent.Type.MouseButtonRelease, p, g, Qt.LeftButton,
                        Qt.NoButton, Qt.NoModifier)
    else:
        e = QWheelEvent(p, g, QPoint(0, 0), QPoint(0, delta), Qt.NoButton,
                        Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(vp, e)


class Stall:
    """4ms 心跳量主线程最长阻塞（掉帧）。"""

    def __init__(self):
        self.gaps = []
        self._last = 0.0
        self.t = QTimer()
        self.t.setInterval(4)
        self.t.setTimerType(Qt.PreciseTimer)
        self.t.timeout.connect(self._tick)

    def _tick(self):
        now = time.perf_counter()
        if self._last:
            self.gaps.append(1000.0 * (now - self._last))
        self._last = now

    def start(self):
        self.gaps = []
        self._last = 0.0
        self.t.start()

    def stop(self):
        self.t.stop()
        return max(self.gaps) if self.gaps else 0.0

    def top(self, n=3):
        """最长的几次停顿（ms，按大小降序）—— 卡顿时用来定位是哪一段。"""
        return sorted(self.gaps, reverse=True)[:n]


def empty_point(mv) -> QPoint:
    vp = mv.viewport()
    for y in range(80, vp.height() - 90, 29):
        for x in range(80, vp.width() - 90, 29):
            if mv.station_at(mv.mapToScene(QPoint(x, y))) is None:
                return QPoint(x, y)
    return QPoint(vp.width() // 2, vp.height() // 2)


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    win.activateWindow()
    pump(400)

    mv = win.map_view
    vp = mv.viewport()
    print(f"主窗口 {win.width()}x{win.height()}  地图视口 {vp.width()}x{vp.height()}  "
          f"scale={mv._scale:.4f}  站点 {len(mv.station_items)}")

    # 收尾计数：_begin_reveal 由 _end_zoom_snap 直接调用，替换属性有效；
    # 定时器连的是构造时的绑定，所以不能靠包装 _apply_station_scale_all 计数。
    counter = {"reveal": 0}
    orig_begin = mv._begin_reveal

    def counted_begin():
        counter["reveal"] += 1
        orig_begin()

    mv._begin_reveal = counted_begin

    # ==================================================================
    # 场景 A：决定性不变量（轮子全发在 p0，随后才拖）
    # ==================================================================
    print("\nA 锚点固定：先滚轮放大，再拖动（拖动必须像素级落地）")
    for tag, wheels, step, moves in (("放大 6 格", 6, 9, 14), ("缩小 4 格", -4, 9, 14)):
        mv._sync_zoom_state()
        pump(300)
        p0 = empty_point(mv)
        asc0 = mv.mapToScene(p0)
        stall = Stall()
        stall.start()
        for _ in range(abs(wheels)):
            ev(vp, "wheel", p0, 120 if wheels > 0 else -120)
            pump(14)
        gesture_ms = stall.stop()          # 纯滚轮阶段

        ev(vp, "press", p0)
        pos, drag = QPoint(p0), 0
        stall.start()
        for _ in range(moves):
            pos = QPoint(pos.x() + step, pos.y() + step)
            drag += step
            ev(vp, "move", pos)
            pump(10)
        move_ms = stall.stop()
        snap = QPointF(mv._snap_pan)
        still_snapping = mv._zoom_snap is not None
        ev(vp, "release", pos)
        stall.start()
        pump(700)
        settle_ms = stall.stop()

        asc_now = mv.mapToScene(pos)
        dev = (abs(asc_now.x() - asc0.x()) * mv._scale,
               abs(asc_now.y() - asc0.y()) * mv._scale)
        print(f"  —— {tag}：拖 {drag}px  _snap_pan=({snap.x():.0f},{snap.y():.0f})  "
              f"滚轮 {gesture_ms:.0f}ms / 拖动 {move_ms:.0f}ms / 收尾 {settle_ms:.0f}ms   "
              f"收尾段最长三次 {[round(v) for v in stall.top()]}")
        ok(f"{tag}：_snap_pan 全额抓到拖动",
           abs(snap.x() - drag) <= 2 and abs(snap.y() - drag) <= 2,
           f"期望 {drag} 实际 {snap.x():.0f}")
        ok(f"{tag}：拖动像素级落地（mapToScene 不变量）", max(dev) < 6.0,
           f"偏差 ({dev[0]:.1f},{dev[1]:.1f}) 屏幕像素"
           f"（0=落地；≈{drag}=拖了白拖）")
        ok(f"{tag}：拖动期间快照仍在（不提前收尾）", still_snapping, "")
        ok(f"{tag}：滚轮阶段不卡（<{GESTURE_STALL_MAX_MS:.0f}ms）",
           gesture_ms < GESTURE_STALL_MAX_MS, f"{gesture_ms:.1f}ms")
        ok(f"{tag}：收尾不卡（<{SETTLE_STALL_MAX_MS:.0f}ms）",
           settle_ms < SETTLE_STALL_MAX_MS, f"{settle_ms:.1f}ms")

    # ==================================================================
    # 场景 B：交错（边滚边拖）
    # ==================================================================
    print("\nB 交错：一边滚轮一边拖（拖动一像素都不能丢）")
    for tag, step, iters in (("放大", 9, 14), ("缩小", 9, 14)):
        mv._sync_zoom_state()
        pump(300)
        p0 = empty_point(mv)
        delta = 120 if tag == "放大" else -120
        n0 = counter["reveal"]
        ev(vp, "press", p0)
        pos, drag = QPoint(p0), 0
        # ★ 先滚一格把快照建立起来，再开始"边滚边拖"：
        #   这也是真人的顺序（先缩放起来、手还在键上，再移动）。
        #   若把这第一格滚轮放在拖动之后，第一次 mouseMove 会走滚动条分支
        #   （那几像素没丢，只是记在滚动条上而非 _snap_pan）→ 计数对不上。
        ev(vp, "wheel", p0, delta)
        stall = Stall()
        stall.start()
        for i in range(iters):
            pos = QPoint(pos.x() + step, pos.y() + step)
            drag += step
            ev(vp, "move", pos)
            ev(vp, "wheel", pos, delta)
            pump(12)
        gesture_ms = stall.stop()
        snap = QPointF(mv._snap_pan)
        during = counter["reveal"] - n0
        still = mv._zoom_snap is not None
        ev(vp, "release", pos)
        stall.start()
        pump(700)
        settle_ms = stall.stop()
        print(f"  —— {tag}：拖 {drag}px  _snap_pan=({snap.x():.0f},{snap.y():.0f})  "
              f"手势 {gesture_ms:.0f}ms / 收尾 {settle_ms:.0f}ms   "
              f"收尾段最长三次 {[round(v) for v in stall.top()]}")
        ok(f"{tag}：拖动一像素都没丢", abs(snap.x() - drag) <= 2
           and abs(snap.y() - drag) <= 2, f"期望 {drag} 实际 {snap.x():.0f}")
        ok(f"{tag}：手势全程不做收尾（快照仍在、收尾次数 0）",
           still and during == 0, f"快照在={still} 收尾={during} 次")
        ok(f"{tag}：手势期间不卡（<{GESTURE_STALL_MAX_MS:.0f}ms）",
           gesture_ms < GESTURE_STALL_MAX_MS, f"{gesture_ms:.1f}ms")
        ok(f"{tag}：收尾不卡（<{SETTLE_STALL_MAX_MS:.0f}ms）",
           settle_ms < SETTLE_STALL_MAX_MS, f"{settle_ms:.1f}ms")

    print(f"\n{'=' * 62}\n通过 {PASS} 项，失败 {FAIL} 项")
    print("全部通过 ✅" if FAIL == 0 else "★ 有失败项")
    win.close()
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
