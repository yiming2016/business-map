# -*- coding: utf-8 -*-
"""收尾一致性探针 v2 —— 正确驱动事件循环。

关键修正：等待/推进必须用 pump()（内部反复 processEvents），
time.sleep 会让 Qt 定时器（_zoom_anim/_zoom_finish）完全不触发，
上一版 diag 的"收尾跳变 1992px"就是这么来的假象。
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


def pump(seconds: float) -> None:
    """真正驱动 Qt 事件循环 seconds 秒（定时器才会触发）。"""
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.004)


pump(0.8)
v.fit_map()
pump(0.5)
print("viewport      :", v.viewport().size(), flush=True)

# --- 拦截收尾：先记录"动画最后一帧"的预测，再看真实帧 ---
orig_apply = MapView._apply_station_scale_all
_rec = {}


def patched(self):
    if self._zoom_snap is not None and not self._zoom_anim.isActive():
        s1 = max(self._scale, 1e-6)
        a = self._snap_anchor
        asc = self._snap_anchor_scene
        _rec["scale_virtual"] = s1
        _rec["anchor"] = a
        _rec["asc"] = QPointF(asc)
        _rec["transform_before"] = self.transform().m11()
        _rec["scroll_before"] = (self.horizontalScrollBar().value(),
                                 self.verticalScrollBar().value())

        def pred(pt):
            return QPointF(asc.x() + (pt.x() - a.x()) / s1,
                           asc.y() + (pt.y() - a.y()) / s1)
        _rec["pred"] = pred
    orig_apply(self)
    _rec["transform_after"] = self.transform().m11()
    _rec["scroll_after"] = (self.horizontalScrollBar().value(),
                            self.verticalScrollBar().value())
    _rec["h_range"] = (self.horizontalScrollBar().minimum(),
                       self.horizontalScrollBar().maximum())
    _rec["v_range"] = (self.verticalScrollBar().minimum(),
                       self.verticalScrollBar().maximum())
    _rec["done"] = True


MapView._apply_station_scale_all = patched


def send_wheel(pt: QPoint, delta=120):
    pos = QPointF(pt)
    e = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, delta),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(v.viewport(), e)


A = QPoint(320, 220)
B = QPoint(950, 640)

send_wheel(A)
pump(0.05)
send_wheel(B)
pump(0.05)
for i in range(2):
    send_wheel(B)
    pump(0.05)

pump(2.5)          # 让动画收敛 + 自动收尾

print("收尾发生了吗    :", _rec.get("done"), flush=True)
if _rec.get("done"):
    print("虚拟scale       :", _rec["scale_virtual"])
    print("收尾后真实scale :", _rec["transform_after"])
    print("快照锚点        :", _rec["anchor"])
    print("锚点场景坐标    :", _rec["asc"])
    print("scroll before   :", _rec["scroll_before"])
    print("scroll after    :", _rec["scroll_after"])
    print("h range after   :", _rec["h_range"])
    print("v range after   :", _rec["v_range"])
    pred = _rec["pred"]
    s1 = _rec["scale_virtual"]
    for name, pt in (("B(950,640)", B), ("A(320,220)", A), ("C(700,430)", QPoint(700, 430))):
        p = pred(pt)
        r = v.mapToScene(pt)
        d = ((r.x() - p.x()) ** 2 + (r.y() - p.y()) ** 2) ** 0.5 * s1
        print(f"  {name:12s} 动画帧={p.x():9.2f},{p.y():9.2f}  真实帧={r.x():9.2f},{r.y():9.2f}  跳变={d:8.2f}px")
