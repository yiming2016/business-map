"""
检查正在运行的 exe 是否处于「未响应」状态，并采样 CPU。

  · IsHungAppWindow(hwnd) —— Windows 官方的"未响应"判定（消息队列 5 秒无响应）
  · 枚举所有顶层窗口（看有没有卡住的弹窗）
  · 用 GetProcessTimes 采样进程 CPU 占用
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.IsHungAppWindow.argtypes = [wt.HWND]
user32.IsHungAppWindow.restype = wt.BOOL
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]

EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

TARGET = "SZ_MetroEditor.exe"

print("=" * 78)
print("① 枚举所有顶层窗口，找本程序的窗口并判定是否『未响应』")
print("=" * 78)

found = []


def cb(hwnd, lparam):
    if not user32.IsWindowVisible(hwnd):
        return True
    n = user32.GetWindowTextLengthW(hwnd)
    if n == 0:
        return True
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    title = buf.value
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    hung = bool(user32.IsHungAppWindow(hwnd))
    found.append((hwnd, pid.value, title, hung))
    return True


user32.EnumWindows(EnumProc(cb), 0)

for hwnd, pid, title, hung in found:
    tag = "🔴 未响应" if hung else "  正常  "
    if "地铁" in title or "站点" in title or "编辑" in title or "新建" in title:
        print(f"  {tag}  hwnd={hwnd:<10} pid={pid:<8} 「{title}」")

print()
print("=" * 78)
print("② 找 SZ_MetroEditor.exe 进程并采样 CPU（3 秒）")
print("=" * 78)

import subprocess
out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {TARGET}", "/FO", "CSV", "/NH"],
                     capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
pids = []
for line in out.strip().splitlines():
    parts = [p.strip('"') for p in line.split('","')]
    if len(parts) >= 2 and parts[1].isdigit():
        pids.append(int(parts[1]))
print(f"  进程 PID = {pids}")

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wt.DWORD), ("dwHighDateTime", wt.DWORD)]


def ft2int(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


for pid in pids:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        print(f"  PID {pid}: 打不开句柄")
        continue

    def times():
        c, e, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                                 ctypes.byref(k), ctypes.byref(u))
        return ft2int(k) + ft2int(u)      # 100ns 单位

    t0 = times()
    w0 = time.perf_counter()
    time.sleep(3.0)
    t1 = times()
    w1 = time.perf_counter()
    cpu = (t1 - t0) / 1e7 / (w1 - w0) * 100.0
    nthreads = ctypes.c_ulong()
    print(f"  PID {pid}: CPU 占用 = {cpu:5.1f}%    （100% ≈ 单核跑满 = 空转/死循环）")
    kernel32.CloseHandle(h)

print()
print("=" * 78)
print("③ 判定")
print("=" * 78)
if any(hung for _, _, t, hung in found if "地铁" in t or "编辑" in t):
    print("  🔴 当前有窗口处于『未响应』状态 —— 复现到了！")
else:
    print("  🟢 当前没有窗口被标记为『未响应』")
print("  提示：CPU 持续接近 100% 说明有定时器/循环在空转，界面会被拖死")
