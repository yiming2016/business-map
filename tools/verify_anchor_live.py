# -*- coding: utf-8 -*-
"""真实鼠标滚轮 + 屏幕真值 验证「以鼠标所在地为原点缩放」。

为什么需要这个工具：
  之前所有验证都是【进程内合成 QWheelEvent】，结论都是"锚点完美(<1px)"，
  但用户仍然反馈"缩放错位"。合成事件与真实输入路径的差别无法排除，
  且"内部计时正常"不等于"屏幕真的在动"。

本工具做三件事（全部真值，无假事件）：
  ① 用 Win32 SendInput 注入【真实滚轮】，驱动【真实 Qt 窗口】（本进程内启动，
     故可把窗口置顶，彻底解决"被浏览器遮挡"导致的测试受阻）；
  ② 用 GDI BitBlt 抓【屏幕真值】，逐帧用模板匹配跟踪指定站点圆点的屏幕位置，
     与"锚点模型"的理论位置比对：
         理论位置 = 锚点 + (起始位置 - 锚点) * (当前缩放 / 起始缩放)
     误差≈0 → 内容真的钉在鼠标下（锚点缩放成立）；误差大 → 复现"内容跑掉"；
  ③ 统计动画期间【相邻屏幕帧的像素差异】—— 区分"画面真的在平滑变化"与
     "画面冻结、停手才跳变"（后者内部计时一切正常，是隐蔽陷阱）；
     并统计收尾后 1.2s 内圆点是否仍在漂移（"错位"的另一种形态）。

用法:
    python tools/verify_anchor_live.py            # 默认 8 格放大
    python tools/verify_anchor_live.py 12 down    # 12 格缩小
"""
import ctypes
import ctypes.wintypes as wt
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# ---------------- Win32 鼠标注入（复用 stutter_probe 的可用实现） ----------------
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
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


def screen_phys():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def move_cursor_phys(x, y):
    sw, sh = screen_phys()
    send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
               int(round(x * 65535 / (sw - 1))), int(round(y * 65535 / (sh - 1))))
    user32.SetCursorPos(int(round(x)), int(round(y)))


def wheel_burst_phys(x, y, notches, up=True, gap=0.02):
    move_cursor_phys(x, y)
    d = WHEEL_DELTA if up else (2 ** 32 - WHEEL_DELTA)
    for _ in range(notches):
        send_mouse(MOUSEEVENTF_WHEEL, 0, 0, d)
        time.sleep(gap)


# ---------------- 屏幕抓取（GDI BitBlt，物理像素） ----------------
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def grab_phys(x, y, w, h):
    """抓屏幕物理像素 (x,y,w,h) -> (h,w,3) uint8 RGB。"""
    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, x, y, 0x00CC0020)
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h          # 负数 = 自上而下
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, hdc)
    a = np.frombuffer(buf.raw, dtype=np.uint8).reshape(h, w, 4)[:, :, 2::-1]
    return np.ascontiguousarray(a)


# ---------------- 模板匹配（粗到细 SSD） ----------------
def match_template(img, tpl, cx, cy, R=260, coarse=4):
    """在 img 中以 (cx,cy) 为中心、半径 R 内找 tpl 最佳位置（像素）。"""
    th, tw = tpl.shape[:2]
    H, W = img.shape[:2]
    x0, x1 = max(0, cx - R), min(W, cx + R + 1)
    y0, y1 = max(0, cy - R), min(H, cy + R + 1)
    win = img[y0:y1, x0:x1].astype(np.float32)
    if win.shape[0] < th or win.shape[1] < tw:
        return None, None

    def scan(step):
        sw = np.lib.stride_tricks.sliding_window_view(win, (th, tw))[::step, ::step]
        d = sw - tpl.astype(np.float32)
        cost = np.einsum("ijkl,ijkl->ij", d, d)
        j, i = np.unravel_index(np.argmin(cost), cost.shape)
        return i * step, j * step, cost

    gi, gj, _ = scan(coarse)         # 粗搜
    fx0 = max(0, gi - coarse)
    fy0 = max(0, gj - coarse)
    sub = win[fy0:fy0 + 2 * coarse + 1, fx0:fx0 + 2 * coarse + 1]
    if sub.shape[0] < th or sub.shape[1] < tw:
        return x0 + gi + tw / 2.0, y0 + gj + th / 2.0
    sw = np.lib.stride_tricks.sliding_window_view(sub, (th, tw))
    d = sw - tpl.astype(np.float32)
    cost = np.einsum("ijkl,ijkl->ij", d, d)
    j, i = np.unravel_index(np.argmin(cost), cost.shape)
    return x0 + fx0 + i + tw / 2.0, y0 + fy0 + j + th / 2.0


# ======================================================================
# 测试主体
# ======================================================================
def main():
    notches = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    direction = (sys.argv[2].lower() if len(sys.argv) > 2 else "up")
    up = direction != "down"

    from PySide6.QtCore import Qt, QPoint, QPointF, QTimer, QMetaObject
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    win = MainWindow()
    win.setWindowFlag(Qt.WindowStaysOnTopHint, True)   # ★ 关键：置顶，杜绝被遮挡
    if win.isMaximized():
        win.showNormal()
    win.setGeometry(60, 60, 1100, 800)
    win.show()
    win.raise_()
    win.activateWindow()

    mv = win.map_view
    mv.setFocus()

    hwnd = int(win.winId())
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)

    result = {}

    def run():
        try:
            _run_test(app, win, mv, hwnd, notches, up, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            result["error"] = repr(e)
        finally:
            QMetaObject.invokeMethod(app, "quit", Qt.QueuedConnection)

    # 等窗口完成首次 fit + 稳定
    def kick():
        if not (getattr(mv, "_first_fit_done", False) and mv.station_items):
            QTimer.singleShot(200, kick)
            return
        threading.Thread(target=run, daemon=True).start()

    QTimer.singleShot(600, kick)
    app.exec()


def _probe_mapping(win, mv):
    """实测 Win32 物理坐标 <-> Qt 逻辑坐标 的换算（DPI 缩放下两者不同）。"""
    a = win.mapToGlobal(QPoint(20, 20))
    b = win.mapToGlobal(QPoint(win.width() - 20, win.height() - 20))
    p1 = (a.x(), a.y())
    move_cursor_phys(0, 0)   # 先动一下，确保 QCursor 刷新
    time.sleep(0.05)
    move_cursor_phys(0, 0)
    time.sleep(0.05)
    from PySide6.QtGui import QCursor
    # 用 win 的两个逻辑角点求 scale/offset：先把自己移动到物理点，再读 Qt 逻辑位置
    return a, b, p1


def _run_test(app, win, mv, hwnd, notches, up, result):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QCursor

    dpr = win.devicePixelRatioF()
    time.sleep(0.3)

    # ---- 1. 物理坐标 <-> 逻辑坐标 映射实测 ----
    wp1 = win.mapToGlobal(QPoint(0, 0))                     # 逻辑
    ref_phys = (10, 10)
    move_cursor_phys(*ref_phys)
    time.sleep(0.08)
    q0 = QCursor.pos()                                      # 逻辑
    kx = (ref_phys[0] - q0.x()) / max(1.0, 0.0) if False else dpr
    # 逻辑 → 物理：phys = ref + dpr * (logical - q0)
    def log2phys(pt):
        return (ref_phys[0] + dpr * (pt.x() - q0.x()),
                ref_phys[1] + dpr * (pt.y() - q0.y()))

    vp = mv.viewport()
    vp_log0 = vp.mapToGlobal(QPoint(0, 0))
    vp_phys0 = log2phys(vp_log0)
    vp_w, vp_h = vp.width(), vp.height()

    # ---- 2. 选锚点：视口中心，且离最近站点圆点足够远（避免 hover 光晕干扰）----
    best = None
    for frac in [(0.5, 0.5), (0.45, 0.55), (0.55, 0.45), (0.4, 0.5), (0.6, 0.5), (0.5, 0.4), (0.5, 0.6)]:
        cand = QPoint(int(vp_w * frac[0]), int(vp_h * frac[1]))
        s = mv.mapToScene(cand)
        it = mv.station_at(s)
        if it is not None:
            continue
        # 最近站点屏幕距离
        dmin, near = 1e9, None
        for sit in mv.station_items.values():
            sp = mv.mapFromScene(sit.pos())
            d = ((sp.x() - cand.x()) ** 2 + (sp.y() - cand.y()) ** 2) ** 0.5
            if d < dmin:
                dmin, near = d, sit
        if dmin < 60:
            continue
        best = (cand, near, dmin)
        break
    if best is None:
        result["error"] = "找不到合适锚点（都离站点太近）"
        return
    anchor_log, track_item, dmin = best

    anchor_phys = log2phys(vp.mapToGlobal(anchor_log))

    # ---- 3. 安全性：该物理点下必须是我们自己的窗口 ----
    pt = wt.POINT(int(anchor_phys[0]), int(anchor_phys[1]))
    hwnd_at = user32.WindowFromPoint(pt)
    pid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd_at, ctypes.byref(pid))
    import os
    if int(pid.value) != os.getpid():
        print(f"!! 锚点物理坐标{pt.x, pt.y} 下的窗口不属于本进程(pid={pid.value})，中止", flush=True)
        result["error"] = "anchor occluded"
        return

    # ---- 4. 抓取区域：覆盖 锚点 与 跟踪站点 的整条运动路径 ----
    track_log = mv.mapFromScene(track_item.pos())
    tr_phys = log2phys(vp.mapToGlobal(track_log))
    pad = 90
    x0 = int(min(anchor_phys[0], tr_phys[0]) - pad)
    y0 = int(min(anchor_phys[1], tr_phys[1]) - pad)
    x1 = int(max(anchor_phys[0], tr_phys[0]) + pad)
    y1 = int(max(anchor_phys[1], tr_phys[1]) + pad)
    x0, y0 = max(0, x0), max(0, y0)
    gw, gh = x1 - x0, y1 - y0
    print(f"[setup] dpr={dpr:.3f} 视口 {vp_w}x{vp_h}(逻辑) 锚点逻辑={anchor_log.x()},{anchor_log.y()}"
          f" 物理={anchor_phys[0]:.1f},{anchor_phys[1]:.1f}", flush=True)
    print(f"[setup] 跟踪站点 {track_item.station_id}（离锚点 {dmin:.0f}px）"
          f" 抓取区 {gw}x{gh} @物理({x0},{y0})", flush=True)

    def in_region(phys_xy):
        return (phys_xy[0] - x0, phys_xy[1] - y0)

    pred_track_phys = tr_phys
    before = grab_phys(x0, y0, gw, gh)
    ax_r = in_region(anchor_phys)      # 锚点在抓取区内的坐标
    tr_r = in_region(tr_phys)

    tpl_half = 14
    tx, ty = int(round(tr_r[0])), int(round(tr_r[1]))
    tpl = before[ty - tpl_half:ty + tpl_half, tx - tpl_half:tx + tpl_half].copy()
    if tpl.shape[0] != 2 * tpl_half or tpl.shape[1] != 2 * tpl_half:
        result["error"] = "站点圆点太靠边，模板越界"
        return
    # 匹配唯一性自检：在初始帧里全图搜一遍，看最佳与次佳差距
    p0 = match_template(before, tpl, tx, ty, R=200)
    print(f"[setup] 模板自检：初始位置匹配=({p0[0]:.1f},{p0[1]:.1f}) 期望=({tr_r[0]:.1f},{tr_r[1]:.1f})"
          f" 误差={((p0[0]-tr_r[0])**2+(p0[1]-tr_r[1])**2)**0.5:.2f}px", flush=True)

    scale0 = mv._scale
    scene_before = mv.mapToScene(anchor_log)
    h0, v0 = mv.horizontalScrollBar().value(), mv.verticalScrollBar().value()

    # ---- 5. 真实滚轮 + 逐帧抓屏 ----
    frames = []          # (t, scale, snap_active, img)
    t_start = time.perf_counter()
    stop = threading.Event()

    def capturer():
        while not stop.is_set():
            s1 = mv._scale
            img = grab_phys(x0, y0, gw, gh)
            s2 = mv._scale
            frames.append((time.perf_counter() - t_start, s1 if s1 == s2 else (s1 + s2) / 2.0,
                           mv._zoom_snap is not None, img))

    th = threading.Thread(target=capturer, daemon=True)
    th.start()
    time.sleep(0.25)                        # 抓一段静止基准
    wheel_burst_phys(anchor_phys[0], anchor_phys[1], notches, up=up, gap=0.02)
    # 等动画+收尾
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 3.5:
        if mv._zoom_snap is None and not mv._zoom_anim.isActive() and 0.6 < time.perf_counter() - t0:
            break
        time.sleep(0.02)
    settle_t = time.perf_counter() - t_start
    time.sleep(1.4)                         # 收尾后继续抓，检测"还在漂"
    stop.set()
    th.join(timeout=2)

    scale_final = mv._scale
    scene_after = mv.mapToScene(anchor_log)

    # ---- 6. 分析 ----
    print("\n================ 结果 ================", flush=True)
    print(f"缩放: {scale0:.4f} -> {scale_final:.4f} (×{scale_final/scale0:.3f})"
          f"  滚动条 h {h0}->{mv.horizontalScrollBar().value()} v {v0}->{mv.verticalScrollBar().value()}", flush=True)
    k = scale_final / scale0
    print(f"锚点场景坐标 前=({scene_before.x():.2f},{scene_before.y():.2f}) "
          f"后=({scene_after.x():.2f},{scene_after.y():.2f}) "
          f"内部漂移={((scene_after.x()-scene_before.x())**2+(scene_after.y()-scene_before.y())**2)**0.5:.2f}场景单位"
          f" (={((scene_after.x()-scene_before.x())**2+(scene_after.y()-scene_before.y())**2)**0.5*scale_final:.2f}px)",
          flush=True)

    pred_final = (ax_r[0] + (tr_r[0] - ax_r[0]) * k, ax_r[1] + (tr_r[1] - ax_r[1]) * k)
    errs_anim, diffs, scales = [], [], []
    prev = None
    for (t, s, snap, img) in frames:
        m = match_template(img, tpl, int(pred_final[0]), int(pred_final[1]), R=90)
        kk = s / scale0
        pred = (ax_r[0] + (tr_r[0] - ax_r[0]) * kk, ax_r[1] + (tr_r[1] - ax_r[1]) * kk)
        if m[0] is not None and snap:
            e = ((m[0] - pred[0]) ** 2 + (m[1] - pred[1]) ** 2) ** 0.5
            errs_anim.append((t, s, e))
        if prev is not None:
            diffs.append((t, float(np.abs(img.astype(np.int16) - prev.astype(np.int16)).mean())))
        prev = img
        scales.append((t, s))

    # 收尾后漂移
    post = []
    for (t, s, snap, img) in frames:
        if t < settle_t:
            continue
        m = match_template(img, tpl, int(pred_final[0]), int(pred_final[1]), R=90)
        if m[0] is not None:
            post.append((t - settle_t, ((m[0] - pred_final[0]) ** 2 + (m[1] - pred_final[1]) ** 2) ** 0.5))

    if errs_anim:
        es = [e for _, _, e in errs_anim]
        print(f"\n动画期间（锚点模型 vs 屏幕真值）样本 {len(es)}："
              f" 均值 {np.mean(es):.2f}px  最大 {np.max(es):.2f}px")
        worst = max(errs_anim, key=lambda x: x[2])
        print(f"  最差帧 t={worst[0]*1000:.0f}ms scale={worst[1]:.4f} 误差={worst[2]:.2f}px")
    else:
        print("\n动画期间：无有效样本（动画没被捕捉到？）")

    if diffs:
        ds = [d for _, d in diffs]
        moving = sum(1 for d in ds if d > 0.4)
        print(f"屏幕帧间差异：均值 {np.mean(ds):.3f}  最大 {np.max(ds):.3f}"
              f"  变化帧占比 {moving}/{len(ds)}（<40% 说明画面基本冻结=动画不可见）")
        # 手势期的差异
        hand = [d for t, d in diffs if t <= settle_t]
        if hand:
            print(f"  其中手势期(t<={settle_t*1000:.0f}ms) 均值 {np.mean(hand):.3f} 最大 {np.max(hand):.3f}")

    if post:
        ps = [e for _, e in post]
        base = ps[0]
        print(f"\n收尾后 1.4s 内圆点位置（相对理论位置）：首样本 {base:.2f}px "
              f"最大 {np.max(ps):.2f}px → 漂移幅度 {np.max(ps)-np.min(ps):.2f}px")

    print(f"\n判定锚点：", end="")
    ok = True
    if errs_anim and np.max([e for _, _, e in errs_anim]) > 8:
        print("✗ 动画期间内容偏离锚点模型（内容没钉在鼠标下）")
        ok = False
    if post and (np.max(ps) - np.min(ps)) > 5:
        print("✗ 收尾后仍在漂移（停手后还能看到错位）")
        ok = False
    if diffs and sum(1 for d in diffs if d > 0.4) < len(diffs) * 0.4:
        print("✗ 动画画面基本冻结（内部计时正常但屏幕不动）")
        ok = False
    if ok:
        print("✓ 通过：内容钉在鼠标处，画面持续变化，收尾后不漂移")
    print("=====================================", flush=True)
    result["ok"] = ok


if __name__ == "__main__":
    main()
