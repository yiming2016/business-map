# -*- coding: utf-8 -*-
"""真机验证"鼠标所在位置为缩放原点" —— 全局边界法（不需要模板匹配）。

为什么不用模板匹配：程序会随缩放档位增删站名标签、文字渲染也随尺寸变化，
画面并非"纯放大"；加上地图上站点圆点/交叉结构大量自相似，
实测同一状态下模板匹配能读出 0.7px 也能读出 237px，完全不可信。

本方法：取地图"彩色线路网"的包围盒（饱和度筛掉背景与深灰站名，只留彩色线路）。
线路网不随缩放档位消失，包围盒极值稳定。设缩放倍率 f（由包围盒尺寸直接量出）：
    · 锚点在鼠标 A：缩放后包围盒中心 = A + (中心₀ - A) · f
    · 锚点错在视图中心 C：缩放后包围盒中心 = C + (中心₀ - C) · f
两者相差 |C - A| · |1 - f|，把 A 选得离 C 远些就有近百像素差距，
而包围盒中心的测量精度只有一两像素。

★★ 必须避开的坑（都是实测踩出来的）：
  1) 【无滚动余量区间】当缩放小到"整个 sceneRect 都塞得进视口"时，
     Qt 滚动条没有可滚范围，锚点原理上无法生效，画面被强制居中——
     此时测出来会"像是锚点在视图中心"。这是视口本身的性质，不是本次 bug。
     → 测量必须在【内容刚好比视口略大一点点】的区间做：
       内容完整可见（不裁切，包围盒才可量），同时 sceneRect 仍大于视口（有滚动余量）。
       本脚本用"包围盒宽度占画布 86%~92%"来锁定这个区间。
  2) 【假通过】滚轮没生效（到缩放上下限、消息没送达）时 before/after 完全相同，
     "位移 0"会被误判成合格 → 必须检查实测倍率 f 明显偏离 1。
  3) 【测点被遮挡】测点若被别的窗口压着，滚轮会发给别的程序 → 先校验归属。
"""
import ctypes
import ctypes.wintypes as wt
import math
import sys
import time

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import numpy as np

user32 = ctypes.windll.user32

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

SAT_MIN = 35            # 彩色判定：max(RGB)-min(RGB) 超过它算"线路"
COL_MIN = 4             # 一列/一行至少这么多彩色像素才算数（滤掉零散抗锯齿）
FAIL_PX = 30.0
MIN_F_DEV = 0.06        # 实测倍率偏离 1 至少这么多，否则认为滚轮没生效
MAP_W_SCENE = 8248.0    # 线路网场景宽度（来自 data，用于换算缩放）

NOTCH_FACTOR = 1.0012 ** 120      # 一格滚轮的倍率


class MI(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("md", wt.DWORD),
                ("fl", wt.DWORD), ("t", wt.DWORD), ("ex", ctypes.POINTER(wt.ULONG))]


class U(ctypes.Union):
    _fields_ = [("mi", MI), ("pad", ctypes.c_byte * 32)]


class INP(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", U)]


def mouse(flags, dx=0, dy=0, data=0):
    i = INP(type=INPUT_MOUSE)
    i.u.mi = MI(dx, dy, data, flags, 0, None)
    user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INP))


def move_to(x, y):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
          int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1)))


def click(x, y):
    move_to(x, y); time.sleep(0.1)
    mouse(MOUSEEVENTF_LEFTDOWN); time.sleep(0.04); mouse(MOUSEEVENTF_LEFTUP)


def wheel(up=True):
    mouse(MOUSEEVENTF_WHEEL, 0, 0, 120 if up else (2 ** 32 - 120))


def info(h):
    b = ctypes.create_unicode_buffer(128); user32.GetWindowTextW(h, b, 128)
    c = ctypes.create_unicode_buffer(64); user32.GetClassNameW(h, c, 64)
    return f"{hex(h)} [{c.value}] {b.value!r}"


def find_exe_window():
    res = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        b = ctypes.create_unicode_buffer(128); user32.GetWindowTextW(h, b, 128)
        c = ctypes.create_unicode_buffer(64); user32.GetClassNameW(h, c, 64)
        if "深圳地铁编辑器" in b.value and c.value.startswith("Qt") \
                and "ToolTip" not in c.value and user32.IsWindowVisible(h):
            res.append(h)
        return True

    user32.EnumWindows(cb, 0)
    return res[0] if res else None


class Screen:
    def __init__(self):
        import dxcam
        self.cam = dxcam.create(output_color="BGRA")
        self.cam.start(target_fps=60, video_mode=True)

    def region(self, x0, y0, x1, y1):
        for _ in range(200):
            f = self.cam.get_latest_frame()
            if f is not None:
                return f[y0:y1, x0:x1, :3].astype(np.float32)
            time.sleep(0.005)
        raise RuntimeError("抓屏失败：2 秒内没有拿到任何帧")

    def stop(self):
        try:
            self.cam.stop()
        except Exception:
            pass


def line_bbox(img):
    """彩色线路网的包围盒（画布内坐标）。返回 (l, t, r, b) 或 None。"""
    sat = img.max(axis=2) - img.min(axis=2)
    mask = sat > SAT_MIN
    xs = np.nonzero(mask.sum(axis=0) >= COL_MIN)[0]
    ys = np.nonzero(mask.sum(axis=1) >= COL_MIN)[0]
    if len(xs) < 10 or len(ys) < 10:
        return None
    return int(xs[0]), int(ys[0]), int(xs[-1]), int(ys[-1])


def main():
    hwnd = find_exe_window()
    if not hwnd:
        print("!! 未找到 exe 窗口（请先启动 SZ_MetroEditor）")
        sys.exit(1)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    r = wt.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    W, H = r.right - r.left, r.bottom - r.top
    print("窗口", (r.left, r.top, r.right, r.bottom), info(hwnd))
    print("前台是不是编辑器 :", user32.GetForegroundWindow() == hwnd)

    pad = 10
    mapL, mapR = int(r.left + W * 0.135) + pad, int(r.left + W * 0.735) - pad
    mapT, mapB = int(r.top + H * 0.075) + pad, int(r.top + H * 0.940) - pad
    CW, CH = mapR - mapL, mapB - mapT
    Cx, Cy = CW / 2.0, CH / 2.0                 # 视图中心（画布坐标）
    print(f"画布 ({mapL},{mapT})-({mapR},{mapB})  尺寸 {CW}x{CH}   视图中心 C=({Cx:.0f},{Cy:.0f})")

    scr = Screen()
    time.sleep(0.6)

    def settle(t=1.7):
        time.sleep(t)

    def bbox():
        return line_bbox(scr.region(mapL, mapT, mapR, mapB))

    def inside(bb, m):
        if bb is None:
            return False
        l, t, rr, b = bb
        return l >= m and t >= m and rr <= CW - m and b <= CH - m

    def send_batch(up, n, gap=0.07):
        for _ in range(abs(int(n))):
            wheel(up); time.sleep(gap)

    def converge_to_width(target_w, anchor_pt, tol=0.03, iters=7):
        """在 anchor_pt 处滚动，把线路网包围盒宽度收敛到 target_w 附近。"""
        bb = None
        for _ in range(iters):
            bb = bbox()
            if bb is None:
                send_batch(True, 4); settle(); continue
            w = bb[2] - bb[0]
            if abs(w - target_w) / target_w <= tol:
                return bb
            n = int(round(math.log(target_w / max(w, 1)) / math.log(NOTCH_FACTOR)))
            if n == 0:
                n = 1 if target_w > w else -1
            n = max(-10, min(10, n))
            move_to(anchor_pt[0], anchor_pt[1]); time.sleep(0.08)
            send_batch(n > 0, n)
            settle()
        return bbox()

    CEN = (int(mapL + Cx), int(mapT + Cy))
    click(CEN[0], CEN[1]); time.sleep(0.4)

    # ---- 第1步：先缩到"整个场景都能装进视口"，此时 Qt 会把场景居中 ----
    #（场景框与内容框同心，所以场景居中 ⇒ 内容居中；不居中就没法可靠量包围盒）
    bb = converge_to_width(CW * 0.60, CEN)
    if bb is None:
        print("!! 无法缩到目标档位")
        scr.stop(); sys.exit(3)

    # ---- 第2步：以画布中心为锚点放大到"内容占画布宽约 70%" ----
    #（这一步是"绕中心"缩放，不会破坏居中；70% 给后面放大 1 格留出不被裁切的余量）
    bb0 = converge_to_width(CW * 0.70, CEN)
    if bb0 is None or not inside(bb0, 25):
        print(f"!! 起始状态线路网不可用或被裁切：{bb0}")
        scr.stop(); sys.exit(3)
    l0, t0, r0, b0 = bb0
    cx0, cy0 = (l0 + r0) / 2.0, (t0 + b0) / 2.0
    s0 = (r0 - l0) / MAP_W_SCENE
    print(f"起始包围盒 ({l0},{t0})-({r0},{b0})  尺寸 {r0-l0}x{b0-t0}  中心 ({cx0:.1f},{cy0:.1f})")
    print(f"推算当前缩放 s ≈ {s0:.4f}（内容占画布宽 {(r0-l0)/CW*100:.0f}%）"
          f"，场景框 {13248*s0:.0f}px vs 视口 {CW}px → 滚动余量 {13248*s0-CW:.0f}px")

    # ---- 第3步：测点 A 取画布左下内侧，尽量离视图中心远 ----
    Ax, Ay = mapL + int(CW * 0.25), mapT + int(CH * 0.72)
    aX, aY = Ax - mapL, Ay - mapT
    dA = ((aX - Cx) ** 2 + (aY - Cy) ** 2) ** 0.5
    print(f"测点 A=({Ax},{Ay})   离视图中心 {dA:.0f}px")
    if user32.WindowFromPoint(wt.POINT(Ax, Ay)) != hwnd:
        print("!! 测点被其它窗口遮挡，已中止（避免误发鼠标事件到别的程序）")
        scr.stop(); sys.exit(2)

    # ---- 第3步：在 A 处放大 1 格，量包围盒怎么动 ----
    move_to(Ax, Ay); time.sleep(0.15)
    wheel(True)
    settle()

    bb1 = bbox()
    if bb1 is None or not inside(bb1, 4):
        print(f"!! 缩放后线路网不可用或被裁切：{bb1}")
        scr.stop(); sys.exit(3)
    l1, t1, r1, b1 = bb1
    fx = (r1 - l1) / max(r0 - l0, 1)
    fy = (b1 - t1) / max(b0 - t0, 1)
    f = (fx + fy) / 2.0
    cx1, cy1 = (l1 + r1) / 2.0, (t1 + b1) / 2.0
    print(f"结束包围盒 ({l1},{t1})-({r1},{b1})  尺寸 {r1-l1}x{b1-t1}  中心 ({cx1:.1f},{cy1:.1f})")
    print(f"实测缩放倍率 f = {f:.4f}  (横向 {fx:.4f} / 纵向 {fy:.4f})")

    if abs(f - 1.0) < MIN_F_DEV:
        print("!! 实测倍率≈1 → 滚轮没生效（可能已到缩放上下限），无法判定")
        scr.stop(); sys.exit(4)

    # 由"同一个内容点缩放前后的位置"反解出实际锚点：
    #   P1 = A + (P0 - A)·f  ⇒  A = (P1 - f·P0) / (1 - f)
    inv = 1.0 / (1.0 - f)
    implied_x = (cx1 - f * cx0) * inv
    implied_y = (cy1 - f * cy0) * inv
    pred_mouse = (aX + (cx0 - aX) * f, aY + (cy0 - aY) * f)
    pred_center = (Cx + (cx0 - Cx) * f, Cy + (cy0 - Cy) * f)
    err_mouse = ((cx1 - pred_mouse[0]) ** 2 + (cy1 - pred_mouse[1]) ** 2) ** 0.5
    err_center = ((cx1 - pred_center[0]) ** 2 + (cy1 - pred_center[1]) ** 2) ** 0.5

    print(f"\n实测包围盒中心       = ({cx1:.1f},{cy1:.1f})")
    print(f"反解出的实际锚点     = ({implied_x:.1f},{implied_y:.1f})  [画布坐标]"
          f"  → 屏幕 ({implied_x + mapL:.0f},{implied_y + mapT:.0f})")
    print(f"鼠标实际所在位置     = ({aX:.1f},{aY:.1f})  [画布坐标]"
          f"  → 屏幕 ({Ax},{Ay})")
    print(f"\n假设『锚点=鼠标』预测 = ({pred_mouse[0]:.1f},{pred_mouse[1]:.1f})   偏差 {err_mouse:.1f}px")
    print(f"假设『锚点=视图中心』预测 = ({pred_center[0]:.1f},{pred_center[1]:.1f})   偏差 {err_center:.1f}px")

    ok = err_mouse <= FAIL_PX and err_mouse < err_center
    print("\n==== 结论 ====")
    print(f"判定：与『锚点=鼠标』预测偏差 ≤{FAIL_PX:.0f}px 且优于『锚点=视图中心』，才算合格。")
    print(f"  锚点在鼠标   : 偏差 {err_mouse:6.1f}px  {'合格' if err_mouse <= FAIL_PX else '不合格'}")
    print(f"  锚点在视图中心: 偏差 {err_center:6.1f}px（错误实现的对照，应明显更大）")
    print("总结:", "缩放严格以鼠标所在位置为原点" if ok else "未通过 —— 缩放原点不是鼠标位置")
    scr.stop()


if __name__ == "__main__":
    main()
