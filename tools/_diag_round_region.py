# -*- coding: utf-8 -*-
"""盯住弹窗的圆角有没有被"弹回去"（区域裁剪的时序问题）。

★ 关于坐标：`QScreen.grabWindow(0)` 返回的是**整屏**位图，但它自己的
   `devicePixelRatio()` 可能是 1.5，而 `QScreen.size()` 是逻辑尺寸。
   换算关系（实测这台机器，150% 缩放）：
       grab 位图宽 2560 = 逻辑宽 1707 × 1.5
   所以 **抓到的位图里，某逻辑点 P 的像素坐标 = P × 1.5**，
   而 `GetWindowRect` 在这个 DPI-unaware 进程里给的**已经是物理像素**。
   两边直接相等即可（不要再乘一次 dpr，那是我上一轮踩的坑）。

用法：python tools/_diag_round_region.py
"""
import ctypes
import ctypes.wintypes as wt
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtCore import QTimer                               # noqa: E402
from PySide6.QtWidgets import QApplication                      # noqa: E402

from ui.edit_dialog import EditDialog                           # noqa: E402

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

app = QApplication(sys.argv)
dlg = EditDialog("车公庙")
dlg.resize(560, 680)
dlg.show()


def win_rect(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def corners_px(hwnd):
    x, y, w, h = win_rect(hwnd)
    img = app.primaryScreen().grabWindow(0).toImage()
    iw, ih = img.width(), img.height()
    # GetWindowRect 给的是物理像素，grab 位图也是物理像素 → 直接用
    def px(a, b):
        if not (0 <= a < iw and 0 <= b < ih):
            return "out-of-range"
        return img.pixelColor(a, b).name()
    return {
        "rect": (x, y, w, h),
        "TL": px(x + 2, y + 2),
        "TR": px(x + w - 3, y + 2),
        "BR": px(x + w - 3, y + h - 3),
        "BL": px(x + 2, y + h - 3),
        "top-mid": px(x + w // 2, y + 2),
    }


def report(tag, img_out=None):
    hwnd = int(dlg.winId())
    # ★ 先截屏、后读 rgn —— 顺序反了读到的会是我们自己刚设的区域
    shot = corners_px(hwnd)
    rgn = gdi32.CreateRectRgn(0, 0, 0, 0)
    box = None
    if user32.GetWindowRgn(hwnd, rgn):
        b = wt.RECT()
        gdi32.GetRgnBox(rgn, ctypes.byref(b))
        box = (b.right, b.bottom)
    print(f"--- {tag} ---")
    print(f"  rgn 尺寸(物理) : {box}")
    print(f"  win rect       : {shot['rect']}")
    print(f"  四角像素        : TL={shot['TL']} TR={shot['TR']} "
          f"BR={shot['BR']} BL={shot['BL']}")
    print(f"  上边中点        : {shot['top-mid']}")
    if img_out:
        from PySide6.QtCore import QRect
        scr_img = app.primaryScreen().grabWindow(0)
        x, y, w, h = shot["rect"]
        scr_img.copy(QRect(x, y, w, h)).save(str(img_out))
        print(f"  已存图          : {img_out}")


def run():
    report("show 之后立刻")
    QTimer.singleShot(150, lambda: report("+150ms"))
    QTimer.singleShot(600, lambda: report("+600ms"))
    QTimer.singleShot(1000, lambda: report(
        "+1000ms（存图）", SRC / "logs" / "_diag_corners.png"))
    QTimer.singleShot(1500, lambda: (
        report("再手动裁一次 → 紧接着取色"),
    ))
    QTimer.singleShot(2000, lambda: (
        report("+500ms，看有没有被弹回去"),
        app.quit(),
    ))


QTimer.singleShot(300, run)
sys.exit(app.exec())
