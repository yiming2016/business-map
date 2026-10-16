# -*- coding: utf-8 -*-
"""真实鼠标滚轮下的锚点验证（关键：打印程序实际收到的鼠标事件坐标）。

在视口内指定一点 A（明显偏离中心）：
  - 记录 A 处场景点 p0
  - 真实 SendInput 把鼠标移到 A、滚 N 格
  - 打印 wheelEvent 收到的 event.position()（看是否等于 A）
  - 等收敛后取 p1 → 漂移像素
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint, QPointF, QTimer

app = QApplication(sys.argv)

from core.data_manager import get_data_manager
from ui.map_view import MapView

user32 = ctypes.windll.user32

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000


class MI(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class U(ctypes.Union):
    _fields_ = [("mi", MI), ("pad", ctypes.c_byte * 32)]


class INP(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("union", U)]


def mouse(flags, dx=0, dy=0, data=0):
    i = INP(type=INPUT_MOUSE)
    i.union.mi = MI(dx, dy, data, flags, 0, None)
    user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INP))


def move_click(x, y):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1)))
    time.sleep(0.15)
    mouse(MOUSEEVENTF_LEFTDOWN); time.sleep(0.03); mouse(MOUSEEVENTF_LEFTUP)
    time.sleep(0.15)


def wheel(up=True):
    mouse(MOUSEEVENTF_WHEEL, 0, 0, 120 if up else (2 ** 32 - 120))


dm = get_data_manager()
v = MapView()
v.setWindowTitle("ANCHORREAL")
v.resize(1400, 900)
v.rebuild_lines()
v.reload_stations(dm.all_stations())
v.show()
v.raise_()
app.processEvents()
time.sleep(0.6)
v.fit_map()
app.processEvents()
time.sleep(0.5)

# ★ 测试窗口必须置顶：否则真实鼠标事件会落到别的窗口上（曾误发到浏览器！）
_hwnd_self = None


@ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
def _cb(h, _):
    global _hwnd_self
    b = ctypes.create_unicode_buffer(128)
    user32.GetWindowTextW(h, b, 128)
    if "ANCHORREAL" in b.value:
        _hwnd_self = h
    return True


user32.EnumWindows(_cb, 0)
if _hwnd_self:
    HWND_TOPMOST = -1
    SWP_NOSIZE, SWP_NOMOVE = 0x0001, 0x0002
    user32.SetWindowPos(_hwnd_self, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE)
    user32.SetForegroundWindow(_hwnd_self)
    time.sleep(0.4)

# 记录程序实际收到的事件坐标
seen = []
_orig_wheel = v.wheelEvent


def wrapped_wheel(ev):
    pos = ev.position() if hasattr(ev, "position") else QPointF(ev.pos())
    seen.append((round(pos.x(), 1), round(pos.y(), 1)))
    return _orig_wheel(ev)


v.wheelEvent = wrapped_wheel

TARGET = QPoint(250, 200)          # 视口内目标点（偏左上，远离中心）
gp = v.viewport().mapToGlobal(TARGET)
print(f"视口 {v.viewport().width()}x{v.viewport().height()}  目标点(视口) {TARGET.x()},{TARGET.y()}  "
      f"→ 屏幕 {gp.x()},{gp.y()}")

move_click(gp.x(), gp.y())
app.processEvents()

p0 = v.mapToScene(TARGET)
s0 = v.transform().m11()
print(f"缩放前 scale={s0:.4f}  A处场景点=({p0.x():.1f},{p0.y():.1f})")

for i in range(5):
    wheel(True)
    t_end = time.time() + 0.09
    while time.time() < t_end:
        app.processEvents()
        time.sleep(0.005)

t_end = time.time() + 1.5
while time.time() < t_end:
    app.processEvents()
    time.sleep(0.01)

p1 = v.mapToScene(TARGET)
s1 = v.transform().m11()
drift = ((p1.x() - p0.x()) ** 2 + (p1.y() - p0.y()) ** 2) ** 0.5 * s1
print(f"缩放后 scale={s1:.4f}  A处场景点=({p1.x():.1f},{p1.y():.1f})")
print(f"★ 锚点漂移 = {drift:.2f} 屏幕px")
print(f"程序实际收到的事件坐标（前5条）: {seen[:5]}")
print(f"期望坐标 = ({TARGET.x()},{TARGET.y()})")
