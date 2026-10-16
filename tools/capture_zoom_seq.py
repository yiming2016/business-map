# -*- coding: utf-8 -*-
"""把一次真实缩放逐帧截下来（真实窗口 + 真实滚轮 + dxcam 抓屏），
用来肉眼确认"错位"到底长什么样。输出 logs/zoomseq/seq_*.png
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, QTimer

app = QApplication(sys.argv)

from core.data_manager import get_data_manager
from ui.map_view import MapView

# 目录重组后不要再写死绝对路径：从本脚本位置往上推
_SUBWAY = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(_SUBWAY, "软件", "logs", "zoomseq")
os.makedirs(OUT, exist_ok=True)

user32 = ctypes.windll.user32

# --- SendInput ---
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("union", _U)]


def _send(flags, dx=0, dy=0, data=0):
    inp = INPUT(type=INPUT_MOUSE)
    inp.union.mi = MOUSEINPUT(dx, dy, data, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def wheel_at(x, y, up=True):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    _send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
          int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1)))
    _send(MOUSEEVENTF_WHEEL, 0, 0, 120 if up else (2 ** 32 - 120))


dm = get_data_manager()
v = MapView()
v.setWindowTitle("ZOOMSEQ")
v.resize(1400, 900)
v.rebuild_lines()
v.reload_stations(dm.all_stations())
v.show()
v.raise_()
app.processEvents()
time.sleep(0.8)
v.fit_map()
app.processEvents()
time.sleep(0.8)


def find_hwnd():
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(hwnd, buf, 128)
        if "ZOOMSEQ" in buf.value:
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value.startswith("Qt"):
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


hwnd = find_hwnd()
if not hwnd:
    print("!! 找不到窗口")
    sys.exit(1)
user32.SetForegroundWindow(hwnd)
time.sleep(0.5)
r = wt.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(r))
print(f"窗口 {r.left},{r.top}-{r.right},{r.bottom}")

import dxcam

region = (r.left + 4 - (r.left + 4) % 2, r.top + 60 - (r.top + 60) % 2,
          r.right - 4 - (r.right - 4) % 2, r.bottom - 60 - (r.bottom - 60) % 2)
cam = dxcam.create(output_color="BGRA")
print("捕获区域", region, region[2] - region[0], "x", region[3] - region[1])

frames = []
stop = [False]
T0 = time.perf_counter()


def collector():
    last = None
    while not stop[0]:
        img = cam.grab(region=region)
        if img is not None:
            t = time.perf_counter() - T0
            frames.append((t, img.copy()))


th = threading.Thread(target=collector, daemon=True)
th.start()
time.sleep(0.5)

gx = (region[0] + region[2]) // 2
gy = (region[1] + region[3]) // 2
print("中心", gx, gy)

# 单格缩放：动画约 200ms，之后收尾
wheel_at(gx, gy, True)
time.sleep(1.0)
stop[0] = True
th.join(timeout=1.0)

print(f"抓到 {len(frames)} 帧")
# 存关键帧：等间隔取 8 张 + 最后一张
from PIL import Image
import numpy as np

sel = []
if frames:
    n = len(frames)
    idxs = sorted(set([int(i * (n - 1) / 9) for i in range(10)] + [n - 1]))
    for i, idx in enumerate(idxs):
        t, img = frames[idx]
        arr = img[:, :, [2, 1, 0]]
        Image.fromarray(arr).save(os.path.join(OUT, f"seq_{i:02d}_t{int(t*1000):04d}ms.png"))
        sel.append((i, t))
print("已保存:", [f"{i}:{int(t*1000)}ms" for i, t in sel])
print("输出目录", OUT)
