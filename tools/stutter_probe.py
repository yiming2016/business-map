# -*- coding: utf-8 -*-
"""顿挫真值探针：dxcam（Desktop Duplication）以桌面刷新粒度记录【真实屏幕帧到达时间】，
同时用真实滚轮事件驱动 exe 缩放。把卡顿时间点与手势阶段（起点/过程/收尾）对齐。

用法: python stutter_probe.py [slow|fast]
输出: 帧到达间隔分布 + 每次 >25ms 停顿的时刻与最近手势事件
"""
import ctypes
import ctypes.wintypes as wt
import sys
import threading
import time

import numpy as np

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

APP_TITLE = "深圳地铁编辑器"

# ---------------- SendInput ----------------
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
WHEEL_DELTA = 120


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("union", _U)]


def send_mouse(flags, dx=0, dy=0, data=0):
    inp = INPUT(type=INPUT_MOUSE)
    inp.union.mi = MOUSEINPUT(dx, dy, data, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def move_cursor(x, y):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
               int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1)))


def wheel_at(x, y, up=True):
    move_cursor(x, y)
    send_mouse(MOUSEEVENTF_WHEEL, 0, 0, WHEEL_DELTA if up else (2 ** 32 - WHEEL_DELTA))


# ---------------- 窗口 ----------------
def find_window():
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(hwnd, buf, 128)
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if (APP_TITLE in buf.value and cls.value.startswith("Qt")
                and "ToolTip" not in cls.value and user32.IsWindowVisible(hwnd)):
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        return None, None
    hwnd = found[0]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
        time.sleep(0.6)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return hwnd, r


def refresh_rate():
    class DEVMODE(ctypes.Structure):
        _fields_ = [("dmDeviceName", ctypes.c_wchar * 32),
                    ("dmSpecVersion", wt.WORD), ("dmDriverVersion", wt.WORD),
                    ("dmSize", wt.WORD), ("dmDriverExtra", wt.WORD),
                    ("dmFields", wt.DWORD),
                    ("dmOrientation", ctypes.c_short), ("dmPaperSize", ctypes.c_short),
                    ("dmPaperLength", ctypes.c_short), ("dmPaperWidth", ctypes.c_short),
                    ("dmScale", ctypes.c_short), ("dmCopies", ctypes.c_short),
                    ("dmDefaultSource", ctypes.c_short), ("dmPrintQuality", ctypes.c_short),
                    ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                    ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
                    ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
                    ("dmLogPixels", wt.WORD), ("dmBitsPerPel", wt.DWORD),
                    ("dmPelsWidth", wt.DWORD), ("dmPelsHeight", wt.DWORD),
                    ("dmDisplayFlags", wt.DWORD), ("dmDisplayFrequency", wt.DWORD)]
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(DEVMODE)
    if user32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm)):
        return dm.dmDisplayFrequency
    return 0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "slow"
    hwnd, r = find_window()
    if not hwnd:
        print("!! 未找到窗口")
        sys.exit(1)
    print(f"窗口 {r.left},{r.top}-{r.right},{r.bottom}  刷新率={refresh_rate()}Hz")

    # 视口区域（去掉标题栏/工具栏/状态栏，取中部）
    cx0 = r.left + int((r.right - r.left) * 0.30)
    cy0 = r.top + int((r.bottom - r.top) * 0.18)
    cx1 = r.right - 8
    cy1 = r.bottom - int((r.bottom - r.top) * 0.10)
    # dxcam region 需偶数
    region = (cx0 - cx0 % 2, cy0 - cy0 % 2, cx1 - cx1 % 2, cy1 - cy1 % 2)
    print("捕获区域", region, f"{region[2]-region[0]}x{region[3]-region[1]}")

    import dxcam
    cam = dxcam.create(output_color="BGRA")
    if cam is None:
        print("!! dxcam 初始化失败")
        sys.exit(1)

    # ---------------- 采集线程 ----------------
    T0 = time.perf_counter()
    events = []      # (t, kind, info)  手势/阶段事件
    arrivals = []    # (t, sig)  新帧到达
    stop = [False]

    def collector():
        while not stop[0]:
            img = cam.grab(region=region)
            if img is not None:
                t = time.perf_counter() - T0
                # 降采样签名（判断画面是否真的变了）
                sig = hash(img[::12, ::12].tobytes())
                arrivals.append((t, sig))

    th = threading.Thread(target=collector, daemon=True)
    th.start()
    time.sleep(0.4)

    # 锚点：视口中心
    ax = (region[0] + region[2]) // 2
    ay = (region[1] + region[3]) // 2
    wheel_at(ax, ay, True)          # 确保焦点
    time.sleep(0.6)
    events.append((time.perf_counter() - T0, "GESTURE-START", mode))

    if mode == "fast":
        # 猛滚：每 50ms 3 格，共 24 次（1.2s）
        for i in range(24):
            for _ in range(3):
                wheel_at(ax, ay, True)
            events.append((time.perf_counter() - T0, "wheel+3", i))
            time.sleep(0.05)
    else:
        # 常规：每 40ms 1 格，共 30 次（1.2s）
        for i in range(30):
            wheel_at(ax, ay, True)
            events.append((time.perf_counter() - T0, "wheel+1", i))
            time.sleep(0.04)

    events.append((time.perf_counter() - T0, "GESTURE-END", ""))
    time.sleep(1.2)                  # 观察收尾
    stop[0] = True
    th.join(timeout=1.0)

    # ---------------- 分析 ----------------
    print(f"\n总帧到达 {len(arrivals)} 次")
    g_start = next(t for t, k, _ in events if k == "GESTURE-START")
    g_end = next(t for t, k, _ in events if k == "GESTURE-END")
    print(f"手势窗口 {g_start:.3f}s ~ {g_end:.3f}s")
    win = [a for a in arrivals if g_start <= a[0] <= g_end + 0.3]
    print(f"手勢窗口内帧数 {len(win)}  → 平均 {len(win)/max(g_end+0.3-g_start,1e-6):.1f} fps")
    deltas = [(b[0] - a[0]) * 1000 for a, b in zip(win, win[1:])]
    if deltas:
        ds = sorted(deltas)
        n = len(ds)
        def pct(p):
            return ds[min(n - 1, int(n * p))]
        print(f"帧到达间隔: 中位 {ds[n//2]:.1f}ms  P90 {pct(0.9):.1f}ms  P99 {pct(0.99):.1f}ms  最大 {ds[-1]:.1f}ms")
        big = [d for d in deltas if d > 25]
        print(f">25ms 的停顿: {len(big)} 次  (占比 {100*len(big)/n:.1f}%)")
        big33 = [d for d in deltas if d > 33]
        big50 = [d for d in deltas if d > 50]
        print(f">33ms(=掉帧): {len(big33)} 次   >50ms(=明显卡顿): {len(big50)} 次")
    # 停顿点位：找 >25ms 的帧间隔，输出其时刻 + 最近手势事件
    print("\n== 停顿明细（>25ms）==")
    cnt = 0
    for a, b in zip(win, win[1:]):
        gap = (b[0] - a[0]) * 1000
        if gap > 25:
            cnt += 1
            prev = [e for e in events if e[0] <= b[0]]
            last_ev = prev[-1] if prev else (0, "?", "")
            phase = []
            if b[0] - g_start < 0.15:
                phase.append("手势起点")
            if g_end - 0.5 <= b[0]:
                phase.append("收尾阶段")
            print(f"  t={b[0]*1000:7.1f}ms 停顿{gap:6.1f}ms  "
                  f"最近事件={last_ev[1]}{last_ev[2]} {'|'.join(phase)}")
            if cnt >= 25:
                print("  ...（截断）")
                break
    # 相同画面连续重复（画面没更新=真正的顿）
    reps = 0
    changes = []
    for a, b in zip(win, win[1:]):
        if a[1] == b[1]:
            reps += 1
        else:
            changes.append((b[0] - a[0]) * 1000)
    print(f"\n画面未变化的相邻帧对: {reps} / {max(len(win)-1,1)}")
    if changes:
        cs = sorted(changes)
        n = len(cs)
        print(f"★ 画面内容更新间隔: 中位 {cs[n//2]:.1f}ms  P90 {cs[int(n*0.9)]:.1f}ms  最大 {cs[-1]:.1f}ms"
              f"  → 有效更新 {1000/max(sum(cs)/n, 1e-6):.0f}fps")


if __name__ == "__main__":
    main()
