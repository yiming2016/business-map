# -*- coding: utf-8 -*-
"""锚点保持实测：在鼠标位置 A 处滚轮缩放，检查 A 处的场景点在缩放
【过程中】和【停手后】是否保持不动（用户要的就是这个）。

测量方式：
  ① 缩放前 在 A 处取场景点 p0
  ② 滚轮放大，等动画收敛、收尾完成
  ③ 缩放后 在 A 处取场景点 p1
  漂移像素 = |p1 - p0| * 最终缩放 —— 应≈0（理想为 0，>2px 肉眼可见）
  ④ 同时检查动画期间：_snap_anchor_scene 是否等于 p0
"""
import os
import sys
import time

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint, QPointF, QTimer
from PySide6.QtGui import QWheelEvent

app = QApplication(sys.argv)

from core.data_manager import get_data_manager
from ui.map_view import MapView

dm = get_data_manager()
v = MapView()
v.setWindowTitle("ANCHORTEST")
v.resize(1400, 900)
v.rebuild_lines()
v.reload_stations(dm.all_stations())
v.show()
app.processEvents()
time.sleep(0.6)
v.fit_map()
app.processEvents()
time.sleep(0.4)

ANCHOR = QPoint(260, 190)     # 明显偏离视口中心
print(f"视口 {v.viewport().width()}x{v.viewport().height()}  锚点(视口坐标) {ANCHOR.x()},{ANCHOR.y()}")


def scene_at(pt: QPoint):
    return v.mapToScene(pt)


def wheel(delta, pos: QPoint):
    p = QPointF(pos)
    e = QWheelEvent(p, p, QPoint(0, 0), QPoint(0, delta),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(v.viewport(), e)


results = []


def round_trip(tag, notches, gap_ms=70, settle_ms=1400):
    app.processEvents()
    p0 = scene_at(ANCHOR)
    s0 = v.transform().m11()
    for i in range(notches):
        wheel(120, ANCHOR)
        app.processEvents()
        t_end = time.time() + gap_ms / 1000.0
        while time.time() < t_end:
            app.processEvents()
    # 观察动画期间的锚点场景坐标
    mid_anchor = None
    if v._zoom_snap is not None:
        mid_anchor = v._snap_anchor_scene
    t_end = time.time() + settle_ms / 1000.0
    while time.time() < t_end:
        app.processEvents()
        time.sleep(0.01)
    p1 = scene_at(ANCHOR)
    s1 = v.transform().m11()
    drift_scene = ((p1.x() - p0.x()) ** 2 + (p1.y() - p0.y()) ** 2) ** 0.5
    drift_px = drift_scene * s1
    snap_err = None
    if mid_anchor is not None:
        snap_err = ((mid_anchor.x() - p0.x()) ** 2 + (mid_anchor.y() - p0.y()) ** 2) ** 0.5 * s0
    print(f"{tag}: scale {s0:.4f} → {s1:.4f}  锚点漂移 {drift_px:7.2f} 屏幕px"
          + (f"   动画锚点误差 {snap_err:.2f}px" if snap_err is not None else ""))
    results.append((tag, drift_px, snap_err))


round_trip("放大5格", 5)
round_trip("再放大5格", 5)
round_trip("缩小8格", -8)

# 换一个锚点再测（右下角）
ANCHOR = QPoint(v.viewport().width() - 120, v.viewport().height() - 90)
print(f"\n换锚点到右下角 {ANCHOR.x()},{ANCHOR.y()}")
round_trip("右下角放大6格", 6)

print("\n==== 结论 ====")
worst = max(results, key=lambda r: r[1])
print(f"最差锚点漂移 = {worst[1]:.2f} 屏幕px （{worst[0]}）")
print("判定：≤2px 合格（滚动条整数取整）；>5px 用户会明显感到'图往中心跑/锚点没钉住'")
