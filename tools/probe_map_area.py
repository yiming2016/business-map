# -*- coding: utf-8 -*-
"""探明地图画布范围：在若干 (x,y) 位置各滚一格，看画面是否变化。

用途：真机验证前，先确认"哪个位置滚轮真的会缩放地图"，
免得把测点选在图例/面板上，量出"0px 位移"这种假合格。
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import numpy as np
import dxcam

u = ctypes.windll.user32
INPUT_MOUSE = 0
MOVE = 0x0001
WHEEL = 0x0800
ABS = 0x8000


class MI(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("md", wt.DWORD),
                ("fl", wt.DWORD), ("t", wt.DWORD), ("ex", ctypes.POINTER(wt.ULONG))]


class U(ctypes.Union):
    _fields_ = [("mi", MI), ("pad", ctypes.c_byte * 32)]


class INP(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", U)]


def mouse(fl, dx=0, dy=0, d=0):
    i = INP(type=INPUT_MOUSE)
    i.u.mi = MI(dx, dy, d, fl, 0, None)
    u.SendInput(1, ctypes.byref(i), ctypes.sizeof(INP))


def move(x, y):
    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    mouse(MOVE | ABS, int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1)))


def wheel():
    mouse(WHEEL, 0, 0, 120)


res = []


@ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
def cb(h, _):
    b = ctypes.create_unicode_buffer(128)
    u.GetWindowTextW(h, b, 128)
    c = ctypes.create_unicode_buffer(64)
    u.GetClassNameW(h, c, 64)
    if "深圳地铁编辑器" in b.value and c.value.startswith("Qt") and "ToolTip" not in c.value:
        res.append(h)
    return True


u.EnumWindows(cb, 0)
if not res:
    print("未找到编辑器窗口")
    sys.exit(1)
hwnd = res[0]
r = wt.RECT()
u.GetWindowRect(hwnd, ctypes.byref(r))
W, H = r.right - r.left, r.bottom - r.top
print("window", (r.left, r.top, r.right, r.bottom), "W,H", W, H)
print("前台窗口是不是编辑器 :", u.GetForegroundWindow() == hwnd)

cam = dxcam.create(output_color="BGRA")
cam.start(target_fps=60, video_mode=True)


def grab(x, y, half=120):
    for _ in range(200):
        f = cam.get_latest_frame()
        if f is not None:
            return f[y - half:y + half, x - half:x + half, :3].astype(np.float32).mean(axis=2)
        time.sleep(0.005)
    raise RuntimeError("no frame")


WIT = (1300, 750)
print("见证点", WIT)
try:
    for y in (300, 750, 1150):
        row = []
        for x in (700, 1100, 1500, 1800, 2000):
            owned = u.WindowFromPoint(wt.POINT(x, y)) == hwnd
            move(x, y)
            time.sleep(0.25)
            b = grab(*WIT)
            wheel()
            time.sleep(0.8)
            a = grab(*WIT)
            diff = float(np.abs(a - b).mean())
            row.append(f"x{x}{'·' if owned else '×'}:{diff:5.1f}")
            move(x, y)
            wheel()
            time.sleep(0.6)
        print(f"  y={y:5d}  " + "  ".join(row))
finally:
    cam.stop()
print("说明：数值明显>0 表示该位置滚轮真的缩放地图；≈0 表示滚轮在该位置不生效")
print("（x 后标 · 表示该点属于编辑器窗口，× 表示被别的窗口挡住）")
