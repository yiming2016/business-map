# -*- coding: utf-8 -*-
"""端到端缩放探针：驱动真实 exe（真实 Windows 滚轮输入）+ 全屏逐帧截图，
检测白屏帧 / 异常帧。不依赖 pywin32，纯 ctypes。

用法:
  python e2e_zoom_probe.py            # 缩小->放大->缩小 三个手势
输出:
  <subway>/软件/logs/e2e_frames/frame_XXXX.png (仅异常帧+首尾帧)
  控制台逐帧报告
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

from PIL import ImageGrab

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

APP_TITLE = "深圳地铁编辑器"
# 目录重组后不要再写死绝对路径：从本脚本位置往上推
_SUBWAY = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(_SUBWAY, "软件", "logs", "e2e_frames")

# ---------- SendInput 定义 ----------
WHEEL_DELTA = 120
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]
    # 其余键盘等字段用字节占位，保证结构体大小正确
    _fields_ += [("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("union", _INPUTunion)]


def send_mouse(flags, dx=0, dy=0, data=0):
    inp = INPUT(type=INPUT_MOUSE)
    inp.union.mi = MOUSEINPUT(dx, dy, data, flags, 0, None)
    ok = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if not ok:
        raise OSError("SendInput failed")


def screen_to_abs(x, y):
    sw = user32.GetSystemMetrics(0)  # SM_CXSCREEN
    sh = user32.GetSystemMetrics(1)
    return int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))


def move_cursor(x, y):
    ax, ay = screen_to_abs(x, y)
    send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, ax, ay)


def click(x, y):
    move_cursor(x, y)
    time.sleep(0.05)
    send_mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.03)
    send_mouse(MOUSEEVENTF_LEFTUP)


def wheel(x, y, delta):
    """在指定屏幕坐标处滚动（先移过去）。delta>0 放大, <0 缩小"""
    move_cursor(x, y)
    send_mouse(MOUSEEVENTF_WHEEL, 0, 0, WHEEL_DELTA if delta > 0 else (2**32 - WHEEL_DELTA))


def find_window():
    """按标题前缀+Qt窗口类名找主窗口，返回 (hwnd, rect)；若最小化先还原"""
    result = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if (APP_TITLE in buf.value and cls.value.startswith("Qt")
                and "ToolTip" not in cls.value and user32.IsWindowVisible(hwnd)):
            result.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    if not result:
        return None, None
    hwnd = result[0][0]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.6)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return hwnd, rect


def analyze(img, bg=(247, 249, 251), tol=6):
    """返回 (非背景像素占比, 白屏判定)。白屏=几乎整幅都是背景色"""
    w, h = img.size
    # 中心区域采样，避开窗口边框/工具栏
    cx0, cy0 = int(w * 0.2), int(h * 0.25)
    cx1, cy1 = int(w * 0.8), int(h * 0.9)
    region = img.crop((cx0, cy0, cx1, cy1)).convert("RGB")
    px = region.tobytes()
    n = len(px) // 3
    nonbg = 0
    for i in range(0, len(px), 3):
        r = px[i]; g = px[i + 1]; b = px[i + 2]
        if abs(r - bg[0]) > tol or abs(g - bg[1]) > tol or abs(b - bg[2]) > tol:
            nonbg += 1
    ratio = nonbg / n
    return ratio, ratio < 0.005


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    hwnd, rect = find_window()
    if not hwnd:
        print("!! 未找到窗口", APP_TITLE)
        sys.exit(1)
    print(f"窗口: {rect.left},{rect.top} - {rect.right},{rect.bottom}")
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)

    cx = (rect.left + rect.right) // 2
    cy = (rect.top + rect.bottom) // 2
    # 点一下空白处，确保焦点在视口
    click(cx, cy)
    time.sleep(0.8)

    frames = []  # (t, ratio, white)
    idx = 0
    t_start = time.perf_counter()

    def grab_and_log(tag):
        nonlocal idx
        img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
        ratio, white = analyze(img)
        t = time.perf_counter() - t_start
        frames.append((t, ratio, white, tag))
        flag = "  << WHITE" if white else ""
        print(f"[{t:7.3f}] {tag:8s} nonbg={ratio*100:6.2f}%{flag}")
        if white or idx % 40 == 0:
            img.save(os.path.join(OUT_DIR, f"frame_{idx:04d}_{tag}.png"))
        idx += 1
        return white

    # 基线
    for _ in range(3):
        grab_and_log("idle")
        time.sleep(0.1)

    mode = sys.argv[1] if len(sys.argv) > 1 else "slow"
    if mode == "fast":
        # 快速连滚：每次抓帧间滚 3 格（接近真人猛滚），放大 45 格再停
        print("--- gesture: FAST ZOOM IN x45 (3 notch/frame) ---")
        for i in range(15):
            for _ in range(3):
                wheel(cx, cy, +1)
            grab_and_log("in")
        for _ in range(24):
            grab_and_log("in-settle")
        # 中途停顿再续：动画收尾后再来一段（触发全新快照）
        print("--- gesture: PAUSE+RESUME ZOOM OUT ---")
        for i in range(8):
            for _ in range(3):
                wheel(cx, cy, -1)
            grab_and_log("out")
        time.sleep(0.35)          # 恰好在收尾窗口边缘
        for _ in range(6):
            grab_and_log("gap")
        for i in range(12):
            for _ in range(3):
                wheel(cx, cy, -1)
            grab_and_log("out2")
        for _ in range(24):
            grab_and_log("out2-settle")
    elif mode == "extreme":
        # 极限：一路放大到 _zoom_max，再一路缩到 _zoom_min
        print("--- EXTREME: zoom in x80 ---")
        for i in range(40):
            for _ in range(2):
                wheel(cx, cy, +1)
            grab_and_log("in")
        for _ in range(24):
            grab_and_log("in-settle")
        print("--- EXTREME: zoom out x120 ---")
        for i in range(60):
            for _ in range(2):
                wheel(cx, cy, -1)
            grab_and_log("out")
        for _ in range(24):
            grab_and_log("out-settle")
    else:
        # 手势1: 快速连续放大 20 格（跨越动画+收尾）
        print("--- gesture: ZOOM IN x20 ---")
        for i in range(20):
            wheel(cx, cy, +1)
            grab_and_log("in")
        # 停手等收尾，高频抓 1.2s
        for _ in range(24):
            grab_and_log("in-settle")
        # 手势2: 快速连续缩小 20 格
        print("--- gesture: ZOOM OUT x20 ---")
        for i in range(20):
            wheel(cx, cy, -1)
            grab_and_log("out")
        for _ in range(24):
            grab_and_log("out-settle")

    whites = [f for f in frames if f[2]]
    print("\n==== 结果 ====")
    print(f"总帧数 {len(frames)}, 白屏帧 {len(whites)}")
    for t, ratio, _, tag in whites:
        print(f"  白屏 @ {t:.3f}s ({tag}) nonbg={ratio*100:.2f}%")


if __name__ == "__main__":
    main()
