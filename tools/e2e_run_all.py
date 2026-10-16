# -*- coding: utf-8 -*-
"""一体化 E2E 测试器：启动 exe → 等窗口 → 跑全部压力手势 → 收尾。
（exe 由本脚本作为子进程启动，测试期间保持存活；命令结束后由调用方决定去留）
"""
import os
import subprocess
import sys
import time
import ctypes
import ctypes.wintypes as wt

# 目录重组后不要再写死绝对路径：从本脚本位置往上推
_TOOLS = os.path.dirname(os.path.abspath(__file__))              # ...\源码\tools
_SUBWAY = os.path.dirname(os.path.dirname(_TOOLS))               # ...\subway
EXE = os.path.join(_SUBWAY, "软件", "SZ_MetroEditor.exe")
sys.path.insert(0, _TOOLS)

user32 = ctypes.windll.user32


def wait_window(timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        found = []
        @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        def cb(hwnd, _):
            buf = ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(hwnd, buf, 128)
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if ("深圳地铁编辑器" in buf.value and cls.value.startswith("Qt")
                    and "ToolTip" not in cls.value and user32.IsWindowVisible(hwnd)):
                found.append(hwnd)
            return True
        user32.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(0.5)
    return None


def main():
    proc = subprocess.Popen([EXE])
    print("exe pid", proc.pid, flush=True)
    hwnd = wait_window()
    if not hwnd:
        print("!! 窗口未出现", flush=True)
        sys.exit(1)
    print("window ok", flush=True)
    time.sleep(1.0)

    import e2e_zoom_probe as probe
    # 依次跑三种模式；每种之间适配窗口归位（模拟用户从全图开始）
    for mode in ("slow", "fast", "extreme"):
        print(f"\n######## MODE {mode} ########", flush=True)
        probe.find_window()
        # 点击空白处聚焦 + 适配窗口，保证起点一致
        probe.user32.SetForegroundWindow(hwnd)
        time.sleep(0.4)
        # 每种模式直接跑（窗口状态延续，真实用户也是连续操作）
        try:
            probe.main.__globals__['sys'].argv = ['x', mode]
            probe.main()
        except SystemExit:
            pass
    print("\nALL MODES DONE", flush=True)


if __name__ == "__main__":
    main()
