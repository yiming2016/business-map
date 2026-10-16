# -*- coding: utf-8 -*-
"""_live_click_probe.py —— 让 verify_anchor_exe.py 真的跑起来（并且真的点在站点上）。

为什么需要它：`verify_anchor_exe.py` 每一步都用 `WindowFromPoint(p) == hwnd`
确认"这个点确实归编辑器窗口"，只要编辑器**不是前台**（被别的窗口压着），
它在取测点那一步就会判定"富结构测点不足"直接退出。
而 `SetForegroundWindow` 受 Windows 前台锁限制：**调用进程必须已经拥有前台权限**。

做法（老技巧，但有效）：在**同一个进程**里先
    按一下 ALT（拿到"最近有输入"的资格）→ ShowWindow 还原 → SetForegroundWindow → 放开 ALT
拿到前台之后再调用 `verify_anchor_exe.main()`，它的 SetForegroundWindow 就能成功。

★ 这个脚本**会真的往编辑器窗口里发鼠标点击和滚轮**（这就是它的目的）。
  它点的位置是"富结构"（站名文字/圆点），因此会落在站点上 —— 也正是
  当初把两条 `_updated_at` 写进用户数据的那两下。
  跑它之前之后都要核对 `软件/data/stations.json` 的 md5 与 mtime。
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import verify_anchor_exe as V

user32 = ctypes.windll.user32
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9


def force_foreground(hwnd) -> bool:
    """把 hwnd 顶到前台，返回是否成功。"""
    if hwnd == user32.GetForegroundWindow():
        return True
    user32.keybd_event(VK_MENU, 0, 0, 0)          # ALT down（解锁前台锁）
    time.sleep(0.05)
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)
    ok = user32.SetForegroundWindow(hwnd)
    time.sleep(0.05)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.35)
    return bool(ok) and user32.GetForegroundWindow() == hwnd


def main() -> None:
    hwnd = V.find_exe_window()
    if not hwnd:
        print("!! 未找到 exe 窗口（请先启动 SZ_MetroEditor）")
        sys.exit(1)
    print("目标窗口：%s" % V.info(hwnd))
    if not force_foreground(hwnd):
        print("!! 抢前台失败，verify_anchor_exe 会在取测点那步退出。")
        print("   （可以先把压在编辑器上的窗口最小化，再重跑本脚本）")
        sys.exit(4)
    print("已把编辑器顶到前台 ✅ —— 接下来它会真的发点击/滚轮")
    V.main()


if __name__ == "__main__":
    main()
