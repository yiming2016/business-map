# -*- coding: utf-8 -*-
"""量"先平移到最边、再缩小"时的鼠标锚点漂移。

场景：滚动条拉到极限（画面被推到场景框边缘）后再滚轮缩小 ——
此时可用余量刚好被吃干，是"缩小会不会漂"的另一个高危路径。
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
# 视口尺寸：默认 1400x900；可传 `890x845` 模拟真实 App 里 874x829 的地图视口
_args = [a for a in sys.argv[1:] if "x" in a and a.split("x")[0].isdigit()]
if _args:
    _w, _h = _args[0].split("x")[:2]
    v.resize(int(_w), int(_h))
else:
    v.resize(1400, 900)
v.rebuild_lines()
v.reload_stations(dm.all_stations())
v.show()

_vpw, _vph = v.viewport().width(), v.viewport().height()
Y = max(2, min(_vph - 2, round(0.80 * _vph)))
XS = (max(2, round(0.15 * _vpw)), max(2, round(0.85 * _vpw)))


def pump(seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.004)


def settle(limit=4.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.processEvents()
        time.sleep(0.004)
        if v._zoom_snap is None and not v._zoom_anim.isActive():
            pump(0.25)
            return True
    return False


def send_wheel(pt, delta=120):
    pos = QPointF(pt)
    e = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, delta),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(v.viewport(), e)


pump(0.8)
v.fit_map()
settle()

worst = 0.0
bad = []

# 四种"顶到边界"的姿态 × 两个鼠标位置
for corner, (hx, vy) in {
        "左边界": (0, None), "右边界": (1, None),
        "上边界": (None, 0), "下边界": (None, 1),
        "左上角": (0, 0), "右下角": (1, 1),
}.items():
    for x in XS:
        pt = QPoint(x, Y)
        v.fit_map()
        settle()
        h, vol = v.horizontalScrollBar(), v.verticalScrollBar()
        if hx is not None:
            h.setValue(h.minimum() if hx == 0 else h.maximum())
        if vy is not None:
            vol.setValue(vol.minimum() if vy == 0 else vol.maximum())
        pump(0.3)
        ref = v.mapToScene(pt)
        mx = 0.0
        for i in range(12):
            send_wheel(pt, -120)
            settle()
            cur = v.mapToScene(pt)
            s = max(v._scale, 1e-9)
            d = ((cur.x() - ref.x()) ** 2 + (cur.y() - ref.y()) ** 2) ** 0.5 * s
            mx = max(mx, d)
        tag = "★漂★" if mx > 1.5 else "OK "
        print(f"  {tag} {corner:<8} 鼠标x={x:<5} 缩到最小最大漂移 {mx:7.2f} px")
        worst = max(worst, mx)
        if mx > 1.5:
            bad.append(f"{corner}/x={x}: {mx:.1f}px")

print("=" * 62)
print(f"最大漂移 {worst:.2f} px   超阈(>1.5px)：{bad or '无'}")
print("=" * 62)
sys.exit(1 if bad else 0)
