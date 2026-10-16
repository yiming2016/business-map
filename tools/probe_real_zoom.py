# -*- coding: utf-8 -*-
"""真实窗口帧率/耗时探针（A/B 计时器分辨率）。

环境变量：
  RTP_1MS=1  → 探针代应用调用 timeBeginPeriod(1)（模拟"修好"的情况）
  RTP_1MS=0  → 不调用（复现应用当前真实情况）

用真实 SendInput 滚轮驱动，记录：_zoom_step 起始间隔（真实帧节奏）、
composition 各段耗时、收尾耗时。
"""
import ctypes
import os
import sys
import threading
import time

os.environ.pop("QT_QPA_PLATFORM", None)      # 真实 windows 平台
USE_1MS = os.environ.get("RTP_1MS", "0") == "1"
if USE_1MS:
    ctypes.windll.winmm.timeBeginPeriod(1)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer, QPoint, QPointF

app = QApplication(sys.argv)

from core.data_manager import get_data_manager
from ui.map_view import MapView

dm = get_data_manager()
v = MapView()
v.setWindowTitle("RTP_PROBE")
v.resize(1400, 900)
v.rebuild_lines()
v.reload_stations(dm.all_stations())
v.show()
app.processEvents()
time.sleep(0.8)
app.processEvents()

# ---------------- SendInput ----------------
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _U)]


user32 = ctypes.windll.user32


def _send(flags, dx=0, dy=0, data=0):
    inp = INPUT(type=INPUT_MOUSE)
    inp.union.mi = MOUSEINPUT(dx, dy, data, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def wheel_at_global(gx, gy, up=True):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    _send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, int(gx * 65535 / (sw - 1)), int(gy * 65535 / (sh - 1)))
    _send(MOUSEEVENTF_WHEEL, 0, 0, 120 if up else (2 ** 32 - 120))


# ---------------- 计时插桩 ----------------
T0 = time.perf_counter()
stats = {
    "step_ts": [],        # 每次 _zoom_step 开始时刻
    "step_cost": [],
    "compose": [],
    "lines": [],
    "label": [],
    "begin": [],
    "final": [],
}
_cur = {}


def wrap(obj, name, key):
    orig = getattr(obj, name)

    def wrapper(*a, **kw):
        s = time.perf_counter()
        r = orig(*a, **kw)
        stats[key].append(1000 * (time.perf_counter() - s))
        return r

    setattr(obj, name, wrapper)


def wrap_step():
    orig = v._zoom_step

    def wrapper():
        t = time.perf_counter()
        stats["step_ts"].append(1000 * (t - T0))
        s = time.perf_counter()
        orig()
        stats["step_cost"].append(1000 * (time.perf_counter() - s))

    v._zoom_step = wrapper


wrap(v, "_compose_frame", "compose")
wrap(v, "_begin_zoom_snap", "begin")
wrap(v, "_apply_station_scale_all", "final")
wrap_step()

# ---- 收尾内部拆解 ----
stats.update({"spr": [], "avs": [], "grab": [], "watch": [], "layout": [], "end": []})
from ui.metro_render import StationDotItem
_w_spr = StationDotItem.render_sprite
StationDotItem.render_sprite = lambda self, *a, **kw: (lambda s: (lambda r: (stats["spr"].append(1000 * (time.perf_counter() - s)), r)[1]))(time.perf_counter())(_w_spr(self, *a, **kw))
_w_avs = StationDotItem.apply_view_scale
StationDotItem.apply_view_scale = lambda self, *a, **kw: (lambda s: (lambda r: (stats["avs"].append(1000 * (time.perf_counter() - s)), r)[1]))(time.perf_counter())(_w_avs(self, *a, **kw))
wrap(v, "_update_label_visibility", "layout")
wrap(v, "_viewport_looks_blank", "watch")
wrap(v, "_end_zoom_snap", "end")
_gr = v.viewport().grab
v.viewport().grab = lambda *a, **kw: (lambda s: (lambda r: (stats["grab"].append(1000 * (time.perf_counter() - s)), r)[1]))(time.perf_counter())(_gr(*a, **kw))

# ★ 定时器在 __init__ 里已连接到原始绑定方法，替换属性不会改变连接 → 重新连到包裹版
v._zoom_anim.timeout.disconnect()
v._zoom_anim.timeout.connect(v._zoom_step)
v._zoom_finish.timeout.disconnect()
v._zoom_finish.timeout.connect(v._apply_station_scale_all)
# 拆：线路层 scene.render 耗时
_sr = v.scene_.render
v.scene_.render = lambda *a, **kw: (lambda s: (lambda r: (stats["lines"].append(1000 * (time.perf_counter() - s)), r)[1]))(time.perf_counter())(_sr(*a, **kw))
# 拆：快照 label 贴图+同步重绘耗时
_lr = v._snap_label.repaint
v._snap_label.repaint = lambda *a, **kw: (lambda s: (lambda r: (stats["label"].append(1000 * (time.perf_counter() - s)), r)[1]))(time.perf_counter())(_lr(*a, **kw))

# ---------------- 手势（应用内定时器 + 合成滚轮，与 probe_zoom 一致，保证必达） ----------------
from PySide6.QtGui import QWheelEvent

anchor = v.viewport().mapToGlobal(QPoint(v.viewport().width() // 2, v.viewport().height() // 2))
gx, gy = anchor.x(), anchor.y()
print(f"viewport {v.viewport().width()}x{v.viewport().height()}  锚点屏幕坐标 ({gx},{gy})  RTP_1MS={USE_1MS}", flush=True)


def wheel_syn(delta):
    pos = QPointF(v.viewport().rect().center())
    e = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, delta),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(v.viewport(), e)


_gs = {"n": 0}
_FAST = os.environ.get("RTP_MODE", "slow") == "fast"


def gesture_tick():
    """slow: 每 40ms 1 格 × 30（1.2s）；fast: 每 50ms 3 格 × 24（1.2s，猛滚）"""
    limit = 24 if _FAST else 30
    if _gs["n"] >= limit:
        return
    _gs["n"] += 1
    if _FAST:
        wheel_syn(120)
        wheel_syn(120)
        wheel_syn(120)
    else:
        wheel_syn(120)


_g_timer = QTimer()
_g_timer.setInterval(50 if _FAST else 40)
_g_timer.timeout.connect(gesture_tick)
QTimer.singleShot(1000, _g_timer.start)
QTimer.singleShot(1000 + (24 if _FAST else 30) * (50 if _FAST else 40), _g_timer.stop)

QTimer.singleShot(3400, app.quit)
app.exec()

# ---------------- 报告 ----------------
ts = stats["step_ts"]
in_win = [t for t in ts if 1000 <= t <= 2200]
gaps = [b - a for a, b in zip(in_win, in_win[1:])]
print(f"\n=== RTP_1MS={USE_1MS} ===")
print(f"_zoom_step 调用 {len(ts)} 次；手势窗口内 {len(in_win)} 次")
if gaps:
    gs = sorted(gaps)
    n = len(gs)
    print(f"帧间隔: 中位 {gs[n//2]:.1f}ms  P90 {gs[int(n*0.9)]:.1f}ms  最大 {gs[-1]:.1f}ms  "
          f"(目标 16ms, 实际 {1000/ (sum(gaps)/n):.1f}fps)")


def rep(key, label):
    arr = stats[key]
    if not arr:
        print(f"{label}: 无数据")
        return
    a = sorted(arr)
    n = len(a)
    print(f"{label}: n={n} 中位 {a[n//2]:.1f}ms  P90 {a[int(n*0.9)]:.1f}ms  最大 {a[-1]:.1f}ms  合计 {sum(arr):.0f}ms")


rep("step_cost", "_zoom_step 总耗时")
rep("compose", "  逐帧合成 compose")
rep("lines", "    线路层 scene.render")
rep("label", "    label 贴图+同步重绘")
rep("begin", "手势起点 begin_snap")
rep("final", "停手收尾 finalize")
rep("spr", "  → 站点 sprite 重建(每次调用)")
rep("avs", "  → apply_view_scale(每次调用)")
rep("layout", "  → 防重叠排版")
rep("watch", "  → 白屏看门狗")
rep("grab", "  → 看门狗 viewport.grab")
rep("end", "  → _end_zoom_snap(含同步重绘)")
