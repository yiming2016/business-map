# -*- coding: utf-8 -*-
"""在真实 exe 上验证"鼠标所在位置为缩放原点"（外部视觉验证，不依赖程序内部状态）。

测量思路（换过两次方法，前两次都不可靠，记录在此避免再走弯路）：
  ✗ 相位相关（phase correlation）：它假设"纯平移"。而缩放是绕锚点【放大】，
    光标那一小块自己也被放大了（1.15~1.33 倍），相关性直接崩——
    实测相关峰只有 0.04~0.08，读数不可信。
  ✓ cv2 多尺度模板匹配：从"缩放前"在光标处取一个小模板（64px），
    去"缩放后"的邻域里多尺度搜索它跑到哪了。
      锚点正确 → 模板原地不动（位移≈0）
      锚点跑偏到视图中心 → 模板会朝外平移 |锚点-视图中心|×(f-1)，可达上百像素
    小模板近似"局部纯平移"，缩放带来的形变很小，匹配峰清晰。

★★★ 重要：本脚本的读数**不能**当判据（v2.5.4 之后）
  站名从 v2.5.4 起会**随缩放变大**（10→20px），而且防重叠排版会随缩放
  增删站名 —— 于是"缩放前后"光标附近的画面**不是纯放大**：
    ① 局部实际缩放 = 视图缩放 × 字号增长比（1.334×1.047 ≈ 1.40），
       而本脚本的倍率搜索范围只有 ×0.97~×1.03，**压根没搜到那个解**；
    ② 地图上到处都是"站名文字"这种相似结构，64px 小模板会匹配到**隔壁的站名**。
  实测：真机读出 121.7px，而同一动作在进程内用 mapToScene 量是 **0.2~0.6px**
  （tools/_chk_zoom_anchor_realvp.py，12 项全过）。
  倍率扫描 tools/_diag_template_fontgrowth.py 也显示"没有任何倍率能自匹配"
  （匹配峰 0.44~0.67 且随倍率单调下降 = 找不到自己）→ 读数不可信。
  ⇒ **权威判据是进程内的 mapToScene 不变量**（同一个点在缩放前后的场景坐标），
    见 tools/_chk_zoom_anchor_realvp.py（真实视口 874×829）。
    本脚本保留下来只为"换个角度看看有没有离谱的宏观错位"。

★★ 两个必须避开的陷阱（都真实踩过）：
  1) 【假通过】滚轮若没生效（已到缩放下限/上限、或消息没送达），
     before/after 完全相同，"位移=0"会被误判成合格。
     → 每轮都测一个【远端对照点 W】：缩放真发生则 W 处画面必定大幅改变。
       W 处纹丝不动 ⇒ 本轮缩放没发生，作废（INVALID）。
  2) 【测点选错】窗口左边缘是"线路图例"、右侧是信息面板，在上面滚轮不缩放地图；
     地图上的大片空白区也没有可跟踪的特征。
     → 测点限制在地图画布内，且要求图像块灰度标准差 ≥ MIN_STD。

抓屏用 dxcam 的 video_mode + get_latest_frame()：普通 grab() 在"画面无新帧"时
返回 None（画面静止时必然如此），会直接毁掉测量。
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import cv2
import numpy as np
from PIL import Image

user32 = ctypes.windll.user32

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

SEARCH = 300            # 邻域搜索半窗（600x600）：必须大于"锚点跑偏"时的理论位移
T_HALF = 32             # 模板半径（64x64 小模板 ≈ 局部纯平移）
WIT_HALF = 200          # 对照点图像块半径
FAIL_PX = 30.0          # 位移超过它 → 没以鼠标为原点
MIN_DIFF = 0.8          # 对照点画面变化量下限（判断"缩放是否真的发生"）
MIN_NCC = 0.35          # 模板匹配峰下限（低于它说明没找到可靠对应）
MIN_GLYPHS = 6          # 测点周围 60px 内的小暗块（笔画/圆点）数量下限：空白区为 0
NOTCHES = 2             # 测量用的滚轮格数

# 目录重组后不要再写死绝对路径：从本脚本位置往上推
_SUBWAY = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.path.join(_SUBWAY, "软件", "logs")


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


def zoom_factor(notches):
    return 1.0012 ** (120 * notches)


class Screen:
    def __init__(self):
        import dxcam
        self.cam = dxcam.create(output_color="BGRA")
        self.cam.start(target_fps=60, video_mode=True)

    def region(self, x0, y0, x1, y1):
        for _ in range(200):
            f = self.cam.get_latest_frame()
            if f is not None:
                return f[y0:y1, x0:x1, :3].astype(np.float32).mean(axis=2)
            time.sleep(0.005)
        raise RuntimeError("抓屏失败：2 秒内没有拿到任何帧")

    def around(self, c, half):
        return self.region(c[0] - half, c[1] - half, c[0] + half, c[1] + half)

    def stop(self):
        try:
            self.cam.stop()
        except Exception:
            pass


def match_shift(before, after, f_guess):
    """在 before/after 两块同尺寸图里，跟踪【中心小模板】跑到哪了。

    返回 (dx, dy, ncc)。dx/dy 相对区域中心（像素）。

    倍率只在小范围内微调（缩放收尾后倍率是精确已知的 f_guess）：
    若把倍率范围放得太宽，模板会被拉到错误尺度、匹配到别的地方去。
    """
    h, w = before.shape
    c = (h // 2, w // 2)
    tmpl0 = before[c[0] - T_HALF:c[0] + T_HALF, c[1] - T_HALF:c[1] + T_HALF]
    if tmpl0.std() < 2.0:
        return 0.0, 0.0, 0.0
    best = None
    for s in np.linspace(f_guess * 0.97, f_guess * 1.03, 5):
        n = int(round(2 * T_HALF * s))
        if n >= min(before.shape) // 2:
            continue
        tmpl = cv2.resize(tmpl0, (n, n), interpolation=cv2.INTER_LINEAR)
        res = cv2.matchTemplate(after, tmpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if best is None or mx > best[0]:
            best = (mx, loc, n)
    if best is None:
        return 0.0, 0.0, 0.0
    mx, loc, n = best
    # 模板中心在 after 里的坐标 → 减去区域中心（=锚点）
    dx = loc[0] + n / 2.0 - c[1]
    dy = loc[1] + n / 2.0 - c[0]
    return dx, dy, float(mx)


def pick_points(hwnd, r, frame):
    """在地图画布内挑测点：必须是"站名文字"那种富结构处。

    ★ 为什么非要文字：直线/圆点这类内容做模板匹配有滑动歧义——
      一条直线沿自身方向能匹配到任意位置，实测会读出几十像素的假位移。
      站名文字是二维富结构，匹配位置唯一。

    三重约束：
      ① 整块 patch 落在画布上、且都属于本程序窗口（左图例/右面板"滚不动"）；
      ② 整块 patch 完整落在屏幕内；
      ③ patch 内的小暗块（笔画/小圆点）数量 ≥MIN_GLYPHS —— 空白区为 0。
    """
    W, H = r.right - r.left, r.bottom - r.top
    mapL, mapR = r.left + W * 0.135, r.left + W * 0.735
    mapT, mapB = r.top + H * 0.075, r.top + H * 0.940
    cx, cy = r.left + W / 2, r.top + H / 2
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    # 找小暗块（文字笔画、站点圆点）作为"有内容"的证据
    inv = (frame < 130).astype(np.uint8)
    n, _, stats, cents = cv2.connectedComponentsWithStats(inv, 8)
    glyphs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if 4 <= w <= 28 and 4 <= h <= 28 and 16 <= area <= 600:
            glyphs.append((x + r.left + w / 2.0, y + r.top + h / 2.0))
    from scipy.spatial import cKDTree
    tree = cKDTree(np.array(glyphs)) if glyphs else None

    def owned(x, y):
        return user32.WindowFromPoint(wt.POINT(int(x), int(y))) == hwnd

    def usable(x, y):
        half = T_HALF
        # 抓图用的 600x600 邻域必须完整落在屏幕内，否则抓到空图
        if x - SEARCH < 0 or y - SEARCH < 0 or x + SEARCH >= sw or y + SEARCH >= sh:
            return False
        # 模板块要落在画布内
        if x - half < mapL or x + half > mapR or y - half < mapT or y + half > mapB:
            return False
        for dy in (-half, 0, half):
            for dx in (-half, 0, half):
                if not owned(x + dx, y + dy):
                    return False
        return True

    def glyph_count(x, y):
        if tree is None:
            return 0
        return len(tree.query_ball_point([x, y], 60))

    cands = []
    y = int(mapT + T_HALF)
    while y < mapB - T_HALF:
        x = int(mapL + T_HALF)
        while x < mapR - T_HALF:
            if usable(x, y) and glyph_count(x, y) >= MIN_GLYPHS:
                cands.append((x, y, glyph_count(x, y)))
                x += 40
            else:
                x += 20
        y += 20
    print(f"  暗块总数 {len(glyphs)}，富结构候选 {len(cands)} 个")
    cands.sort(key=lambda p: -(((p[0] - cx) ** 2 + (p[1] - cy) ** 2) ** 0.5))
    return [c[:2] for c in cands], (cx, cy)


def main():
    hwnd = find_exe_window()
    if not hwnd:
        print("!! 未找到 exe 窗口（请先启动 SZ_MetroEditor）")
        sys.exit(1)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    r = wt.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    print("窗口", (r.left, r.top, r.right, r.bottom), info(hwnd))
    print("前台是不是编辑器 :", user32.GetForegroundWindow() == hwnd)

    scr = Screen()
    time.sleep(0.6)

    def settle(t=1.7):
        time.sleep(t)

    # 先把缩放拉离上限：若已在上限，再向上滚等于没动作，
    # before/after 完全相同 → 会量出"位移 0"的假合格。
    mid_pt = ((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    click(mid_pt[0], mid_pt[1]); time.sleep(0.4)
    move_to(mid_pt[0], mid_pt[1]); time.sleep(0.1)
    for _ in range(3):
        wheel(False); time.sleep(0.1)
    settle()

    frame = scr.region(r.left, r.top, r.right, r.bottom)
    pts, (cx, cy) = pick_points(hwnd, r, frame)
    if len(pts) < 3:
        print(f"!! 富结构测点不足（{len(pts)} 个），"
              "请先关掉压在编辑器上的浏览器、并确保地图上有内容")
        scr.stop()
        sys.exit(3)
    print(f"可用测点 {len(pts)} 个（钉在'站名文字'等富结构处）")

    def far_from(p, pool, min_d, exclude=()):
        best, bd = None, -1
        for q in pool:
            if q in exclude:
                continue
            d = ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5
            if d >= min_d and d > bd:
                best, bd = q, d
        return best

    A = pts[0]                                   # 锚点（离中心最远）
    W1 = far_from(A, pts, 380) or pts[-1]        # 对照点
    P2 = far_from(A, pts, 420, exclude=(W1,)) or pts[-1]
    P3 = far_from(P2, pts, 420, exclude=(W1,)) or pts[len(pts) // 2]
    print(f"A={A}  W1={W1}   P2={P2}  P3={P3}")

    for p in (A, W1, P2, P3):
        if user32.WindowFromPoint(wt.POINT(p[0], p[1])) != hwnd:
            print(f"!! 测点 {p} 被遮挡，已中止（避免误发鼠标事件到别的程序）")
            scr.stop()
            sys.exit(2)

    results = []

    def verdict(name, shift, ncc, wit_diff, theory_bad):
        print(f"  对照点画面变化量 = {wit_diff:.2f}   （>{MIN_DIFF} 才说明缩放真的发生）")
        if wit_diff < MIN_DIFF:
            print("  !! 对照点画面没变 → 本轮缩放没发生，作废（INVALID）")
            results.append((name, None))
            return
        if ncc < MIN_NCC:
            print(f"  !! 匹配峰 {ncc:.3f} < {MIN_NCC} → 没找到可靠对应，读数不可信（作废）")
            results.append((name, None))
            return
        print(f"  参考：若锚点跑偏，此处理论应移动约 {theory_bad:.0f}px")
        results.append((name, shift))

    # ================= 场景 1：鼠标停在 A 不动，滚轮放大 =================
    bA = scr.around(A, SEARCH)
    bW = scr.around(W1, WIT_HALF)
    move_to(A[0], A[1]); time.sleep(0.1)
    for _ in range(NOTCHES):
        wheel(True); time.sleep(0.13)
    settle()
    aA = scr.around(A, SEARCH)
    aW = scr.around(W1, WIT_HALF)

    dx, dy, ncc = match_shift(bA, aA, zoom_factor(NOTCHES))
    d_main = (dx * dx + dy * dy) ** 0.5
    d_wit = float(np.abs(aW - bW).mean())
    distA = ((A[0] - cx) ** 2 + (A[1] - cy) ** 2) ** 0.5
    print(f"\n★ 场景1  鼠标停在 A={A} 滚 {NOTCHES} 格放大")
    print(f"  A 处跟踪位移 = ({dx:+.1f},{dy:+.1f})px  模长 {d_main:.1f}px  匹配峰 {ncc:.3f}")
    # ★ 只报数、不判定：见文件顶部说明（站名会随缩放变大 → 模板匹配必然失准）
    print("  ★ 本读数仅供参考、不作判定（站名随缩放变大，模板尺度对不上）")
    print("     权威判据：python tools/_chk_zoom_anchor_realvp.py（mapToScene 直接量）")
    verdict("场景1 鼠标停在原地缩放(参考)", d_main, ncc, d_wit,
            distA * (1 - 1 / zoom_factor(NOTCHES)))
    # 存一张对比图便于人工复核
    ih = min(bA.shape[0], aA.shape[0])
    Image.fromarray(np.hstack([bA[:ih], aA[:ih]]).astype(np.uint8)).save(
        LOG + r"\anchor_pair.png")

    time.sleep(0.6)

    # ===== 场景2：滚一下 → 挪到别处再滚（用户报的"错位"动作） =====
    click(P2[0], P2[1]); time.sleep(0.4)
    move_to(P2[0], P2[1]); time.sleep(0.05)
    wheel(True)                       # 起手：此刻锚点落在 P2
    time.sleep(0.06)
    move_to(P3[0], P3[1]); time.sleep(0.04)
    wheel(True)                       # 挪到 P3 后继续滚 —— 锚点应改到 P3
    mid = scr.around(P3, SEARCH)      # "挪过来那一刻"的画面
    midW = scr.around(W1, WIT_HALF)
    for _ in range(2):
        wheel(True); time.sleep(0.13)
    settle()
    end = scr.around(P3, SEARCH)
    endW = scr.around(W1, WIT_HALF)

    dx2, dy2, ncc2 = match_shift(mid, end, zoom_factor(2))
    d2 = (dx2 * dx2 + dy2 * dy2) ** 0.5
    d2w = float(np.abs(endW - midW).mean())
    print(f"\n★ 场景2  在 P2={P2} 滚 1 格 → 挪到 P3={P3} 再滚 3 格")
    print(f"  P3 处跟踪位移（挪过来那一刻 → 停手）= ({dx2:+.1f},{dy2:+.1f})px  "
          f"模长 {d2:.1f}px  匹配峰 {ncc2:.3f}")
    print(f"  对照点画面变化量 = {d2w:.2f}")
    # ★ 本场景只做参考、不参与判定：
    #   程序会随缩放档位增删站名标签，"挪过来那一刻"到"停手"之间画面不是纯放大，
    #   外部模板匹配精度有限（实测噪声可达一两百像素）。
    #   该动作的权威结论来自进程内端到端测量：tools/diag_mouse_anchor.py 场景3
    #   （用真实 mapToScene 核对，实测 0.49px）。
    print("  （本项仅供人工参考，不作为判定依据；权威结果见 diag_mouse_anchor.py 场景3）")

    scr.stop()

    print("\n==== 真机读数（仅参考） ====")
    print(f"如果真要判定：位移 ≤{FAIL_PX:.0f}px 合格（理想 0px）；"
          f"匹配峰 ≥{MIN_NCC}、对照点变化量 ≥{MIN_DIFF} 才算有效。")
    for name, s in results:
        # ★ 一律只报数、不判合格：见文件顶部「本脚本的读数不能当判据」
        if s is None:
            print(f"  {name}: 作废（测量退化或缩放未发生）")
        else:
            print(f"  {name}: {s:6.1f} px  ← 参考值，别拿它判合格/不合格")
    print("总结: 本脚本只提供「宏观错位」的旁证，**不作为判定依据**。")
    print("      权威判据 → python tools/_chk_zoom_anchor_realvp.py"
          "（真实视口 874×829，用 mapToScene 直接量，锚点应为 0~1px）")
    print("      读数为什么不可信 → python tools/_diag_template_fontgrowth.py")


if __name__ == "__main__":
    main()
