# -*- coding: utf-8 -*-
"""决定性实验：在某点连滚 4 格，量【整窗】变化量 + 前后台窗口信息。

若滚轮真的缩放地图，整窗变化量会很大（几十）；
只有鼠标悬停高亮之类的小变化则只有个位数。
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

# 目录重组后不要再写死绝对路径：从本脚本位置往上推
_SUBWAY = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LOG_DIR = os.path.join(_SUBWAY, "软件", "logs")

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import numpy as np
import dxcam

u = ctypes.windll.user32
INPUT_MOUSE = 0
MOVE = 0x0001
LD = 0x0002
LU = 0x0004
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


def wheel(up=True):
    mouse(WHEEL, 0, 0, 120 if up else (2 ** 32 - 120))


def click(x, y):
    move(x, y)
    time.sleep(0.1)
    mouse(LD)
    time.sleep(0.04)
    mouse(LU)


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


def tname(h):
    b = ctypes.create_unicode_buffer(128)
    u.GetWindowTextW(h, b, 128)
    return b.value[:40]


u.EnumWindows(cb, 0)
hwnd = res[0]
r = wt.RECT()
u.GetWindowRect(hwnd, ctypes.byref(r))
print("window", (r.left, r.top, r.right, r.bottom))

cam = dxcam.create(output_color="BGRA")
cam.start(target_fps=60, video_mode=True)


def grab(region):
    x0, y0, x1, y1 = region
    for _ in range(200):
        f = cam.get_latest_frame()
        if f is not None:
            return f[y0:y1, x0:x1, :3].astype(np.float32).mean(axis=2)
        time.sleep(0.005)
    raise RuntimeError("no frame")


def fg(tag):
    h = u.GetForegroundWindow()
    print(f"  [{tag}] 前台 = {hex(h)} {tname(h)!r}  是编辑器={h == hwnd}")


P = (int(r.left + (r.right - r.left) * 0.5), int(r.top + (r.bottom - r.top) * 0.5))
print("测点 P =", P, "该点属于编辑器 =",
      u.WindowFromPoint(wt.POINT(*P)) == hwnd)
fg("初始")

click(*P)
time.sleep(0.5)
fg("点击后")

region = (r.left, r.top, r.right, r.bottom)
b = grab(region)
move(*P)
time.sleep(0.15)
for _ in range(4):
    wheel(True)
    time.sleep(0.15)
time.sleep(1.8)
a = grab(region)
fg("滚轮后")

d = float(np.abs(a - b).mean())
print(f"\n整窗平均变化量 = {d:.2f}   （缩放发生 → 通常几十；只有悬停高亮 → 个位数）")
np.save(os.path.join(_LOG_DIR, "whole_before.npy"), b)
np.save(os.path.join(_LOG_DIR, "whole_after.npy"), a)
cam.stop()
