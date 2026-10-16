# -*- coding: utf-8 -*-
"""抓一张"正在运行的打包版 exe"的窗口截图（验证打包产物，不是源码）。

★ 默认走 `PrintWindow`（让窗口把自己画到我给的内存 DC 上）——
  这条路**不需要窗口在最前面**，也不会被系统的"前台锁"拦住，最稳。
  老办法（置前 + 整屏截图）保留在 `--screen` 后面当备选。

用法：
    python tools/_shot_running_exe.py            # 输出 logs/_running_exe.png
    python tools/_shot_running_exe.py --screen   # 用"置前+整屏"的老办法
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtCore import QTimer, QPoint                    # noqa: E402
from PySide6.QtGui import QImage, QPixmap                    # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
TITLE_KEYWORD = "深圳地铁编辑器"


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def _grab_by_printwindow(hwnd: int, w: int, h: int) -> QPixmap:
    """★★ 坑（2026-09-24 新踩的）：置前截图在本环境里**两条路都断了** ——
    `SetForegroundWindow` 被前台锁静默拦掉，连 `SetWindowPos(HWND_TOPMOST)`
    这次也返回 0（失败），于是整屏截图抓到的还是压在 App 上面的浏览器。
    改用 `PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT)`：
    由**窗口自己**把内容画进我们准备的 DC，完全不关心 z-order，返回 1 即成功。
    实测 Qt 窗口能拿到完整真实画面（采样 40x40 网格有 110 种颜色，不是黑屏）。
    """
    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    gdi32.SelectObject(mem_dc, bmp)

    PW_RENDERFULLCONTENT = 0x00000002
    ok = user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)
    print(f"[PrintWindow] 返回 {ok}（1 = 成功）")

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h            # 负数 = 自顶向下
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0        # BI_RGB
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    return QPixmap.fromImage(
        QImage(buf, w, h, w * 4, QImage.Format_RGB32).copy())


def find_window() -> int:
    """枚举顶层窗口，找标题里含关键词、且可见的那个。"""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if TITLE_KEYWORD in buf.value:
            found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        return 0
    hwnd, title = found[0]
    print(f"[FOUND] hwnd={hwnd} title={title!r}")
    return hwnd


def main() -> int:
    app = QApplication(sys.argv)
    use_screen = "--screen" in sys.argv
    hwnd = find_window()
    if not hwnd:
        print(f"[ERROR] 没找到标题含 {TITLE_KEYWORD!r} 的窗口，exe 可能没在跑")
        return 1

    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    x, y = rect.left, rect.top
    w, h = rect.right - rect.left, rect.bottom - rect.top

    if use_screen:
        # ── 备选路：置前 + 整屏截图（需要窗口真在最前面才行）──
        user32.ShowWindow(hwnd, 9)              # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.8)

        # ★★ 坑（2026-09-24 踩的）：`SetForegroundWindow` 会被系统的"前台锁"**静默拦掉** ——
        #   本进程不是当前前台进程时，这个调用等于没调，窗口仍压在别的窗口后面，
        #   于是截出来的是**压在它上面的那个窗口**（实测截到了一整个浏览器里的抖音页面，
        #   看着像"App 界面全变了"）。所以要先验前台窗口换没换；
        #   没换成就试 `SetWindowPos(HWND_TOPMOST)`。
        #   ★ 但这条也不保险：2026-09-24 实测它返回 0（失败）——所以默认不用这条路。
        topmost = False
        if user32.GetForegroundWindow() != hwnd:
            HWND_TOPMOST = -1
            SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
            print("[TOPMOST] SetForegroundWindow 被系统拦了，改用 TOPMOST 置前")
            ok = user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                     SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            print(f"[TOPMOST] SetWindowPos 返回 {ok}（0 = 失败）")
            topmost = True
            time.sleep(0.8)

        try:
            print(f"[RECT] {w}x{h} @ ({x},{y})  前台窗口={user32.GetForegroundWindow()}")
            scr = QApplication.primaryScreen()
            full = scr.grabWindow(0)
            dpr = full.devicePixelRatio() or 1.0
            # ★ 坑：本进程是 DPI-unaware 的，GetWindowRect 拿到的已经是**物理像素**；
            #   而 grabWindow 返回的 QPixmap 也是物理像素。所以这里**不能再乘 dpr**，
            #   乘了会把裁剪区放大 1.5 倍、偏到右下角去（右侧/下方露出桌面）。
            pm = full.copy(int(x), int(y), int(w), int(h))
            tag = f"dpr={dpr}"
        finally:
            if topmost:                          # 撤掉 TOPMOST，别给用户留个"永远最前"的窗口
                HWND_NOTOPMOST = -2
                SWP_NOMOVE, SWP_NOSIZE = 0x0002, 0x0001
                user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE)
                print("[TOPMOST] 已撤销")
    else:
        # ── 默认路：PrintWindow，不要求窗口在最前面 ──
        print(f"[RECT] {w}x{h} @ ({x},{y})  前台窗口={user32.GetForegroundWindow()}"
              f"（不是本窗口也没关系）")
        pm = _grab_by_printwindow(hwnd, w, h)
        tag = "PrintWindow"

    out = SRC / "logs" / "_running_exe.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    # ★★ 坑（2026-09-24 踩的）：`QPixmap.save()` 失败时**只返回 False、不抛异常** ——
    #   不看返回值就会打印"[OK]"却什么都没写出来，还以为"截到了"。
    if not pm.save(str(out)):
        print(f"[ERROR] 截图保存失败：{out}")
        return 2
    print(f"[OK] {out}  ({pm.width()}x{pm.height()} {tag})")

    QTimer.singleShot(0, app.quit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
