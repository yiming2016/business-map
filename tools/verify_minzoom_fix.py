# -*- coding: utf-8 -*-
"""验证 v2.4.4 修复：缩到最小之后再放大，是否严格以鼠标为原点。

复现用户报告的场景（进程内合成滚轮事件，走真实 wheelEvent 入口）：
  1) fit 适配 → 2) 一路缩到缩不动 → 3) 逐格放大，逐格核对
     "鼠标像素点下面的场景坐标"有没有变。
  没变 = 严格以鼠标为原点；变了 = 错位，打印偏差像素数。

同时核对"滚动条是否始终有余量"，这是锚点能成立的前提。
"""
import os
import sys
import time

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

app = QApplication(sys.argv)

from core.data_manager import get_data_manager
from ui.map_view import MapView

dm = get_data_manager()
v = MapView()
v.resize(1400, 900)
v.rebuild_lines()
v.reload_stations(dm.all_stations())
v.show()

FAILS = []


def pump(seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.004)


def settle(limit=4.0):
    """等缩放动画 + 收尾定时器全部落定。"""
    t0 = time.time()
    while time.time() - t0 < limit:
        app.processEvents()
        time.sleep(0.004)
        if v._zoom_snap is None and not v._zoom_anim.isActive():
            pump(0.25)          # 留出收尾/清 sprite 的时间
            return True
    return False


def send_wheel(pt, delta=120):
    pos = QPointF(pt)
    e = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, delta),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(v.viewport(), e)


def degenerate():
    """当前是否已落进"sceneRect*scale ≦ 视口 → 滚动条无余量"的退化区间。"""
    sr = v.scene_.sceneRect()
    vp = v.viewport()
    return sr.width() * v._scale <= vp.width() or sr.height() * v._scale <= vp.height()


def scroll_room():
    h, vol = v.horizontalScrollBar(), v.verticalScrollBar()
    return (h.maximum() - h.minimum(), vol.maximum() - vol.minimum())


def state(tag):
    vp = v.viewport()
    sr = v.scene_.sceneRect()
    room = scroll_room()
    print(f"  {tag:<22} scale={v._scale:.5f}  sceneRect*scale={sr.width()*v._scale:7.1f}x"
          f"{sr.height()*v._scale:7.1f}  视口={vp.width()}x{vp.height()}  "
          f"滚动余量 h/v={room[0]}/{room[1]}  {'★退化★' if degenerate() else '正常'}")
    return room


def anchor_check(pt, tag, tol=1.5):
    """滚动前后，pt 像素下的场景坐标是否钉住。返回偏移像素。"""
    before = v.mapToScene(pt)
    send_wheel(pt, 120)
    ok = settle()
    after = v.mapToScene(pt)
    s = max(v._scale, 1e-9)
    err = ((after.x() - before.x()) ** 2 + (after.y() - before.y()) ** 2) ** 0.5 * s
    flag = "OK " if err <= tol else "★错位★"
    print(f"  {flag} {tag:<22} 偏移 {err:7.2f} px   (动画落定={ok}, scale={v._scale:.5f})")
    if err > tol:
        FAILS.append(f"{tag}: 偏移 {err:.2f}px")
    return err


pump(0.8)
v.fit_map()
settle()
print("\n===== 1. 适配视图 =====")
state("fit")
print(f"  缩放下限 = {v._min_scale_for_viewport():.5f}  (硬下限 _zoom_min = {v._zoom_min})")
if degenerate():
    FAILS.append("fit 状态就已退化，测试前提不成立（滚动条无余量）")

A = QPoint(1000, 700)
print(f"\n鼠标测点 A = {A}")

print("\n===== 2. 一路缩到缩不动（40 格，远超下限） =====")
for _ in range(40):
    send_wheel(A, -120)
    pump(0.05)
settle()
room = state("缩到最小")
if degenerate():
    FAILS.append("缩到最小后仍处于退化区间（滚动条无余量）")
if room[0] <= 0 or room[1] <= 0:
    FAILS.append(f"缩到最小后滚动条无余量 h/v={room}")

print("\n===== 3. 从最小逐格放大，逐格核对鼠标锚点 =====")
base = v.mapToScene(A)
print(f"  起点：A 下场景点 = ({base.x():.2f}, {base.y():.2f})")
for i in range(12):
    anchor_check(A, f"放大第 {i+1} 格")
    if degenerate():
        FAILS.append(f"放大第 {i+1} 格后落入退化区间")

print("\n===== 4. 换一个靠近视口右下的鼠标位置再试 =====")
B = QPoint(1200, 760)
for _ in range(40):
    send_wheel(B, -120)
    pump(0.05)
settle()
state("缩到最小(B)")
for i in range(6):
    anchor_check(B, f"B 放大第 {i+1} 格")

print("\n===== 5. 窗口拉大后，下限自动抬高（不落回退化区间） =====")
for _ in range(40):
    send_wheel(A, -120)
    pump(0.05)
settle()
old_scale = v._scale
state("小窗口缩到最小")
v.resize(1900, 1300)
settle()
print(f"  拉窗口后 scale {old_scale:.5f} → {v._scale:.5f}   "
      f"新下限={v._min_scale_for_viewport():.5f}  (旧上限视口 {v.viewport().width()}x{v.viewport().height()})")
state("拉大窗口后")
if degenerate():
    FAILS.append("拉大窗口后落入退化区间（_enforce_zoom_floor 没生效）")
for i in range(5):
    anchor_check(A, f"拉大后放大第 {i+1} 格")

print("\n" + "=" * 62)
if FAILS:
    print(f"结果：★失败★ {len(FAILS)} 项")
    for f in FAILS:
        print("   -", f)
    sys.exit(1)
print("结果：★全部通过★ 缩到最小→放大全程严格以鼠标为原点")
print("=" * 62)
