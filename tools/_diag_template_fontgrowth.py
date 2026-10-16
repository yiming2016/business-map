# -*- coding: utf-8 -*-
"""_diag_template_fontgrowth.py —— 为什么外部像素验证会读出"上百像素的假位移"。

背景：`tools/verify_anchor_exe.py` 用 64px 小模板做多尺度匹配来跟踪
"光标下的画面跑到哪了"。它的倍率搜索范围只有 `f_guess*(0.97~1.03)`
（f_guess = 滚轮格数推出的**视图**缩放）。

但从 v2.5.4 起，站名会**随缩放变大**（10→20px）——
于是光标附近那块图像的实际缩放 = 视图缩放 × 字号增长比，
**超出搜索范围**，模板匹配就落到别的字形上，读出几十~上百像素的假位移。

本脚本把倍率**扫一遍**，看匹配峰落在哪个倍率、那时的位移是多少：
  - 如果峰出现在 ~1.4×f_guess 且**位移≈0** → 证实是"模板尺度没跟上"，
    锚点本身没问题（权威判据见 tools/_chk_zoom_anchor_realvp.py）。
  - 如果峰在 f_guess 附近且位移就是上百像素 → 那才是真故障。

★ 本脚本**只动鼠标和滚轮，不点任何键**（点击会触发业务落盘）。
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import verify_anchor_exe as V
from _live_click_probe import force_foreground

NOTCHES = 2
F = V.zoom_factor(NOTCHES)          # 视图缩放（脚本原本假设的局部缩放）


def main() -> None:
    hwnd = V.find_exe_window()
    if not hwnd:
        print("!! 未找到 exe 窗口（请先启动 SZ_MetroEditor）")
        sys.exit(1)
    print("目标窗口：%s" % V.info(hwnd))
    if not force_foreground(hwnd):
        print("!! 抢前台失败（先最小化压在编辑器上的窗口再试）")
        sys.exit(4)

    import ctypes
    import ctypes.wintypes as wt
    r = wt.RECT()
    V.user32.GetWindowRect(hwnd, ctypes.byref(r))

    scr = V.Screen()
    time.sleep(0.8)
    # 先拉离上限（否则向上滚没动作，before/after 一样 → 假合格）
    mid = ((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    V.move_to(*mid)
    for _ in range(3):
        V.wheel(False)
        time.sleep(0.1)
    time.sleep(1.7)

    frame = scr.region(r.left, r.top, r.right, r.bottom)
    pts, _ = V.pick_points(hwnd, r, frame)
    if not pts:
        print("!! 找不到富结构测点")
        scr.stop()
        sys.exit(3)
    A = pts[0]
    print("测点 A = %s（视图缩放 f_guess = %.3f）" % (A, F))

    before = scr.around(A, V.SEARCH)
    V.move_to(A[0], A[1])
    time.sleep(0.1)
    for _ in range(NOTCHES):
        V.wheel(True)
        time.sleep(0.13)
    time.sleep(1.7)
    after = scr.around(A, V.SEARCH)
    scr.stop()

    # 确认这一轮缩放真的发生了（否则 before/after 相同 → 位移 0 的假合格）
    diff = float(np.abs(after - before).mean())
    print("画面变化量 %.2f（很小说明这轮缩放没发生，读数无效）" % diff)

    h, w = before.shape
    c = (h // 2, w // 2)
    t0 = before[c[0] - V.T_HALF:c[0] + V.T_HALF, c[1] - V.T_HALF:c[1] + V.T_HALF]
    if t0.std() < 2.0:
        print("!! 模板太平（std=%.2f），换测点重试" % t0.std())
        sys.exit(3)

    import cv2
    print("\n%10s %10s %10s %10s" % ("倍率", "相对f", "匹配峰NCC", "位移px"))
    best = None
    for k in np.arange(0.94, 1.62, 0.02):
        s = F * float(k)
        n = int(round(2 * V.T_HALF * s))
        if n >= min(before.shape) // 2 or n < 8:
            continue
        tmpl = cv2.resize(t0, (n, n), interpolation=cv2.INTER_LINEAR)
        res = cv2.matchTemplate(after, tmpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        dx = loc[0] + n / 2.0 - c[1]
        dy = loc[1] + n / 2.0 - c[0]
        d = (dx * dx + dy * dy) ** 0.5
        mark = ""
        if best is None or mx > best[0]:
            best = (mx, k, d)
            mark = "  <"
        print("%10.2f %10.2f %10.3f %10.1f%s" % (s, k, mx, d, mark))

    print("\n峰值：倍率 ×%.2f（= 视图缩放 %.3f × 字号增长 %.3f）  匹配峰 %.3f  位移 %.1fpx"
          % (best[1], F, best[1], best[0], best[2]))
    print("脚本当前只搜 ×0.97~×1.03 → 它取到的是**非峰值**那个解，位移虚高。")
    print("权威结论请用：python tools/_chk_zoom_anchor_realvp.py（mapToScene 直接量，不靠像素）")


if __name__ == "__main__":
    main()
