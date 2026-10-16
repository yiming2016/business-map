# -*- coding: utf-8 -*-
"""量"缩小过程中鼠标锚点有没有漂" —— 这是"缩小到最小会错位"的直接量化。

判据：把鼠标放在某点不动，一路缩小；如果锚点成立，鼠标下的【场景坐标】
     应当全程不变。因此每一步都核对 mapToScene(鼠标) 相对起点的偏移。

同时打印滚动条 range：若收尾时需要的滚动位置超出 range，Qt 会 clamp，
这一刻画面就会漂 —— 这就是"缩小到最小的时候会错位"的机制。
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

STEPS = 14

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


def room():
    h, vol = v.horizontalScrollBar(), v.verticalScrollBar()
    return h.maximum() - h.minimum(), vol.maximum() - vol.minimum()


def need_vs_range(pt, asc):
    """收尾需要的滚动位置是否落在滚动条 range 之外（= 会被 clamp = 会漂）。"""
    s = v._scale
    h, vol = v.horizontalScrollBar(), v.verticalScrollBar()
    sx = asc.x() * s - pt.x()
    sy = asc.y() * s - pt.y()
    ox = max(0, h.minimum() - sx) + max(0, sx - h.maximum())
    oy = max(0, vol.minimum() - sy) + max(0, sy - vol.maximum())
    return ox, oy


pump(0.8)
v.fit_map()
settle()

fit_scale = v._scale
print(f"适配视图 scale={fit_scale:.5f}  视口={v.viewport().width()}x{v.viewport().height()}")
print(f"（缩放下限={v._min_scale_for_viewport():.5f}）\n")

worst = 0.0
bad_positions = []

# 鼠标测点按【视口比例】取（0=最左, 1=最右），这样换任何窗口尺寸都落在窗口内
_vpw, _vph = v.viewport().width(), v.viewport().height()
_fracs = [0.06, 0.28, 0.50, 0.72, 0.94]
POSITIONS = [max(2, min(_vpw - 2, round(f * _vpw))) for f in _fracs]
Y = max(2, min(_vph - 2, round(0.80 * _vph)))
print(f"鼠标测点横坐标（视口宽 {_vpw}）= {POSITIONS}   y={Y}\n")

for x in POSITIONS:
    pt = QPoint(x, Y)
    v.fit_map()
    settle()
    ref = v.mapToScene(pt)
    print(f"---- 鼠标 x={x}  (起点场景 {ref.x():.1f},{ref.y():.1f}) ----")
    mx = 0.0
    for i in range(STEPS):
        send_wheel(pt, -120)
        settle()
        cur = v.mapToScene(pt)
        s = max(v._scale, 1e-9)
        d = ((cur.x() - ref.x()) ** 2 + (cur.y() - ref.y()) ** 2) ** 0.5 * s
        ox, oy = need_vs_range(pt, ref)
        r = room()
        mx = max(mx, d)
        flag = "  ★漂★" if d > 1.5 else ""
        print(f"  第{i+1:2d}格 scale={s:.5f} 偏移={d:7.2f}px  滚动余量 h/v={r[0]}/{r[1]}  超出range={ox:.0f},{oy:.0f}{flag}")
    print(f"  → x={x} 最大漂移 {mx:.2f} px\n")
    if mx > worst:
        worst = mx
    if mx > 1.5:
        bad_positions.append(x)

print("=" * 62)
print(f"最大漂移 {worst:.2f} px   超阈(>1.5px)的鼠标位置: {bad_positions or '无'}")
print("=" * 62)
sys.exit(1 if bad_positions else 0)
