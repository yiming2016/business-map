# -*- coding: utf-8 -*-
"""鼠标锚点测试：缩放必须以【鼠标当前位置】为原点 —— 光标下的地图内容不许跑。

场景 1：鼠标不动，连滚多格 —— 光标下的点应始终不动。
场景 2：鼠标在 A 滚一下 → 立刻把鼠标移到 B 再滚 —— B 点下的内容不许跑
        （这是真机最常见的动作：滚一下、挪个位置、再滚）。
场景 3：动画帧 → 真实帧 收尾不许跳（不许在松手瞬间"啪"地弹一下）。

★ 血泪教训（v2 修正）：推进必须用 pump()，它内部反复 processEvents。
  time.sleep 期间 Qt 事件循环被阻塞，_zoom_anim/_zoom_finish 这两个 QTimer
  一次都不会触发 —— 动画根本没跑完，收尾函数又因 _zoom_anim.isActive()
  直接早退，于是量出上千 px 的"假跳变"，白白排查了很久。
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
v.setWindowTitle("MOUSEANCHOR")
v.resize(1400, 900)
v.rebuild_lines()
v.reload_stations(dm.all_stations())
v.show()


def pump(seconds: float) -> None:
    """真正驱动 Qt 事件循环 seconds 秒（QTimer 才会触发）。"""
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.004)


pump(0.8)
v.fit_map()
pump(0.5)

results = []


def send_wheel(pt: QPoint, delta=120):
    pos = QPointF(pt)
    e = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, delta),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(v.viewport(), e)


def displayed_scene_under(pt: QPoint):
    """当前【屏幕上显示的画面】里，pt 处对应哪个场景点。

    动画期间屏幕上是合成帧：screen = anchor + (scene - anchor_scene) * _scale
    所以 scene = anchor_scene + (pt - anchor) / _scale
    """
    if v._zoom_snap is None:
        return v.mapToScene(pt)
    s1 = max(v._scale, 1e-6)
    a = v._snap_anchor
    asc = v._snap_anchor_scene
    return QPointF(asc.x() + (pt.x() - a.x()) / s1,
                   asc.y() + (pt.y() - a.y()) / s1)


def drift_px(pt: QPoint, scene_before: QPointF) -> float:
    s1 = max(v._scale, 1e-6)
    now = displayed_scene_under(pt)
    dx = (now.x() - scene_before.x()) * s1
    dy = (now.y() - scene_before.y()) * s1
    return (dx * dx + dy * dy) ** 0.5


# ---------------- 场景 1：鼠标不动，连滚 6 格 ----------------
A = QPoint(320, 220)
send_wheel(A)                      # 首格：建立快照
pump(0.03)
assert v._zoom_snap is not None, "快照未建立"
sA0 = displayed_scene_under(A)
worst1 = 0.0
for i in range(6):
    send_wheel(A)
    pump(0.04)
    worst1 = max(worst1, drift_px(A, sA0))
print(f"场景1 鼠标不动连滚6格：光标下内容最大漂移 {worst1:.2f} px", flush=True)
results.append(("场景1 鼠标固定", worst1))
pump(1.2)                          # 等收尾

# ---------------- 场景 2：A 滚一下 → 移到 B 再滚 ----------------
B = QPoint(950, 640)
send_wheel(A)
pump(0.03)
sB0 = displayed_scene_under(B)     # 移到 B 之前，B 点下的内容
send_wheel(B)                      # 鼠标已移到 B 再滚
pump(0.03)
d_b = drift_px(B, sB0)
print(f"场景2 鼠标移到新位置再滚：新位置(B)下内容漂移 {d_b:.2f} px", flush=True)
results.append(("场景2 移动后新位置", d_b))

worst2 = d_b
for i in range(2):
    send_wheel(B)
    pump(0.04)
    worst2 = max(worst2, drift_px(B, sB0))
print(f"场景2 继续在 B 滚2格：B 下内容累计漂移 {worst2:.2f} px", flush=True)
results.append(("场景2 持续滚", worst2))

# ---------------- 场景 3：收尾瞬间 动画帧 → 真实帧 不许跳 ----------------
old = v._apply_station_scale_all
_cap = {}


def hooked():
    if v._zoom_snap is not None and not v._zoom_anim.isActive():
        s1 = max(v._scale, 1e-6)
        a = v._snap_anchor
        asc = v._snap_anchor_scene
        _cap["pred"] = QPointF(asc.x() + (B.x() - a.x()) / s1,
                               asc.y() + (B.y() - a.y()) / s1)
        _cap["s1"] = s1
    old()


v._apply_station_scale_all = hooked
pump(2.5)
v._apply_station_scale_all = old

if "pred" in _cap:
    p = _cap["pred"]
    r = v.mapToScene(B)
    jump = ((r.x() - p.x()) ** 2 + (r.y() - p.y()) ** 2) ** 0.5 * _cap["s1"]
else:
    jump = float("nan")
print(f"收尾瞬间 B 点内容跳变 {jump:.2f} px", flush=True)
results.append(("收尾跳变", jump))

# ---------------- 场景 3：滚一下 → 挪位置 → 再滚（端到端，用真实映射核对） ----------------
# 这是用户报的"错位"动作。判据：挪到新位置滚第一格时，光标下被钉住的场景点，
# 到全部收敛后必须【还在同一屏幕位置】。用真实 mapToScene 核对，像素级精度。
P2 = QPoint(300, 200)
P3 = QPoint(1100, 700)
send_wheel(P2)          # 起手：锚点 = P2
pump(0.06)
send_wheel(P3)          # 挪到 P3 后滚第一格 → 应把锚点改到 P3
pump(0.03)
pinned = displayed_scene_under(P3)   # 这一格之后，P3 下被钉住的场景点
send_wheel(P3)
pump(0.04)
send_wheel(P3)
pump(2.4)                            # 动画收敛 + 收尾
real = v.mapToScene(P3)
_scale_now = max(v._scale, 1e-6)
d3 = (((real.x() - pinned.x()) ** 2 + (real.y() - pinned.y()) ** 2) ** 0.5) * _scale_now
print(f"场景3 滚一下→挪到新位置→再滚：钉住的场景点最终偏移 {d3:.2f} px（屏幕像素）", flush=True)
results.append(("场景3 挪位置后续滚(端到端)", d3))

print("\n==== 结论 ====")
print("理想值：全部 ≈ 0px。>3px 用户就会明显感到「缩放不跟鼠标、画面往旁边跑」。")
for name, val in results:
    flag = "  ← 不合格" if val > 3 else ""
    print(f"  {name}: {val:8.2f} px{flag}")
