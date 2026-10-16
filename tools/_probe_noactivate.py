# -*- coding: utf-8 -*-
"""
验证"自动拉起 exe 时不抢焦点"——用 Win32 前台窗口作为客观判据。

判据：拉起前记下前台窗口 hwnd，拉起 8 秒后再看前台是谁。
      ★ 只要拉起后前台 **不是** MetroEditor 主窗口 ⇒ 没抢焦点（PASS）。
      （不看"前后是否同一个窗口"：自动化宿主常常没有前台窗口，
        桌面/任务栏会当替补，前后不同是正常的。）

用法:
    python tools/_probe_noactivate.py
"""
import ctypes
import os
import subprocess
import sys
import time

from ctypes import wintypes

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

_SUBWAY = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE = os.path.join(_SUBWAY, "软件", "SZ_MetroEditor.exe")
EXPLORER = r"C:\Windows\explorer.exe"


def title_of(hwnd):
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    u32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def pid_of(hwnd):
    pid = wintypes.DWORD(0)
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def proc_name(pid):
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL).decode("gbk", errors="ignore")
        for line in out.splitlines():
            if line.startswith('"'):
                return line.split(",")[0].strip('"')
    except Exception:
        pass
    return "?"


def running():
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq SZ_MetroEditor.exe", "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL).decode("gbk", errors="ignore")
    except Exception:
        return []
    return [l.split(",")[1].strip('"') for l in out.splitlines()
            if l.startswith('"SZ_MetroEditor.exe"')]


def kill_all():
    n = 0
    for pid in running():
        subprocess.call(["taskkill", "/PID", pid, "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        n += 1
    return n


def find_metro_hwnd():
    """枚举顶层窗口，找主窗口标题含『深圳地铁编辑器』的那个。"""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        t = title_of(hwnd)
        if t and "深圳地铁编辑器" in t:
            found.append((hwnd, t))
        return True

    u32.EnumWindows(cb, 0)
    return found[0] if found else (0, "")


def main():
    kill_all()
    time.sleep(0.6)

    fg_before = u32.GetForegroundWindow()
    print(f"[BEFORE] 前台 hwnd={fg_before} 标题={title_of(fg_before)!r} "
          f"进程={proc_name(pid_of(fg_before))}({pid_of(fg_before)})")

    flag = os.path.join(os.path.dirname(EXE), ".noactivate")
    with open(flag, "w", encoding="ascii") as f:
        f.write("1")
    print("[FLAG] 已写标记:", flag)

    subprocess.Popen([EXPLORER, EXE])
    time.sleep(9)

    pids = running()
    mhwnd, mtitle = find_metro_hwnd()
    fg_after = u32.GetForegroundWindow()
    print(f"[AFTER ] 前台 hwnd={fg_after} 标题={title_of(fg_after)!r} "
          f"进程={proc_name(pid_of(fg_after))}({pid_of(fg_after)})")
    print(f"[METRO ] hwnd={mhwnd} 标题={mtitle!r} PID={pids}")

    ok = True
    if not pids:
        print("[FAIL] 进程没起来")
        ok = False
    if not mhwnd:
        print("[FAIL] 找不到主窗口")
        ok = False
    if mhwnd and fg_after == mhwnd:
        print("[FAIL] 拉起后前台**就是** MetroEditor ⇒ 抢焦点了")
        ok = False
    else:
        print("[PASS] 拉起后前台**不是** MetroEditor ⇒ 没有抢焦点")
    if os.path.isfile(flag):
        print("[WARN] 标记文件没被消费（exe 没读到 .noactivate，机制可能失效）")
        ok = False
    else:
        print("[PASS] 标记文件已被 exe 消费并删除")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
