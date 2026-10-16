# -*- coding: utf-8 -*-
"""探针：缩到最小（场景比视口还小）时，视图的真实映射关系是什么？

要弄清两件事：
  1) 手写公式 scene = (scroll + screen)/scale 在这个区间还成不成立？
     （_begin_zoom_snap 就是用这个公式算快照锚点的场景坐标的）
  2) 滚动条范围是否真的塌成 0 → 也就是"以鼠标为原点"能不能被满足。
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


def pump(seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.004)


pump(0.8)
v.fit_map()
pump(0.5)


def send_wheel(pt, delta=120):
    pos = QPointF(pt)
    e = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, delta),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(v.viewport(), e)


def dump(tag):
    h = v.horizontalScrollBar()
    vol = v.verticalScrollBar()
    s = v._scale
    m = v.mapToScene(0, 0)
    pred = QPointF(h.value() / s, vol.value() / s)
    vp = v.viewport()
    sr = v.scene_.sceneRect()
    print(f"\n---- {tag} ----")
    print(f"scale             = {s:.6f}   (zoom_min={v._zoom_min})")
    print(f"viewport          = {vp.width()}x{vp.height()}")
    print(f"sceneRect         = ({sr.x():.1f},{sr.y():.1f}) {sr.width():.1f}x{sr.height():.1f}")
    print(f"sceneRect*scale   = {sr.width()*s:.1f}x{sr.height()*s:.1f}  "
          f"(比视口{'大' if sr.width()*s > vp.width() else '小'})")
    print(f"h scroll value/range = {h.value()} / [{h.minimum()}, {h.maximum()}]")
    print(f"v scroll value/range = {vol.value()} / [{vol.minimum()}, {vol.maximum()}]")
    print(f"mapToScene(0,0)      = ({m.x():.2f},{m.y():.2f})")
    print(f"手写公式 scroll/scale = ({pred.x():.2f},{pred.y():.2f})")
    dx = m.x() - pred.x(); dy = m.y() - pred.y()
    print(f"两者差 (场景单位)     = ({dx:.2f},{dy:.2f})  → 屏幕 {dx*s:.2f},{dy*s:.2f} px")
    print(f"两者是否一致          = {'是' if abs(dx) < 0.5 and abs(dy) < 0.5 else '★否★'}")


A = QPoint(1000, 700)
print("光标测点 A =", A, " mapToScene(A) =", v.mapToScene(A))

dump("适配视图（初始）")

# 一路缩到最小
for i in range(40):
    send_wheel(A, -120)
    pump(0.012)
pump(2.5)
dump("缩到最小之后")

print("\n缩到最小后，A 下的场景点 =", v.mapToScene(A))

# 再从最小放大 1 格，看 A 下的场景点有没有变（不变=以鼠标为原点）
before = v.mapToScene(A)
send_wheel(A, 120)
pump(2.5)
after = v.mapToScene(A)
s = max(v._scale, 1e-9)
err = ((after.x() - before.x()) ** 2 + (after.y() - before.y()) ** 2) ** 0.5 * s
print(f"\n从最小放大 1 格：A 下场景点 前={before.x():.1f},{before.y():.1f} "
      f"后={after.x():.1f},{after.y():.1f}  偏移 {err:.2f} px")
dump("放大 1 格之后")
