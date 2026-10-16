# -*- coding: utf-8 -*-
"""验证【真实用法】下弹窗的圆角：EditDialog 是挂在主窗口上的（有 parent）。

有 parent 时 Qt 会按样式表的 border-radius 自己把四角挖成透明，
这条路径必须单独验一遍（不能只验无 parent 的独立窗口）。

做法：启动主窗口 → 通过主窗口真的调出编辑弹窗 → 整屏截图 → 看弹窗四角
是不是"主窗口的背景色"而不是弹窗自己的底色。

用法：python tools/_chk_dialog_corners_real.py
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtCore import Qt, QTimer                           # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog             # noqa: E402

from ui.main_window import MainWindow                           # noqa: E402
from ui.edit_dialog import EditDialog                           # noqa: E402

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1480, 900)
win.show()

state = {}


def open_dialog():
    """用真实路径打开编辑弹窗（有 parent），拿不到就退回最常见的那条。"""
    dlg = EditDialog(station_id="车公庙", parent=win)
    dlg.show()
    dlg.raise_()
    state["dlg"] = dlg
    QTimer.singleShot(700, shoot)


def shoot():
    dlg = state["dlg"]
    app.processEvents()
    scr = QApplication.primaryScreen()

    # ★★ 坐标单位是这个脚本最大的坑，务必按下面来：
    #   · `GetWindowRect`（本进程 DPI-unaware）拿到的**已经是物理像素**；
    #   · `QScreen.grabWindow(0)` 返回的位图**也是物理像素**
    #     （位图宽 = QScreen.size()×dpr，例：1707×1.5 ≈ 2560）；
    #   · 所以两边**直接用，绝不能再乘 dpr** —— 乘了裁剪区会偏到右下角，
    #     看起来就像"圆角没生效"（本项目为此白查了两轮）。
    import ctypes
    import ctypes.wintypes as wt
    rect = wt.RECT()
    ctypes.windll.user32.GetWindowRect(int(dlg.winId()), ctypes.byref(rect))
    x, y = rect.left, rect.top
    w, h = rect.right - rect.left, rect.bottom - rect.top

    full = scr.grabWindow(0)
    pm = full.copy(x, y, w, h)
    out = SRC / "logs" / "_dialog_corners_real.png"
    pm.save(str(out))

    img = pm.toImage()
    W, H = img.width(), img.height()

    def px(x, y):
        return img.pixelColor(x, y).name()

    dlg_bg = "#f7f8fa".lower()

    def is_dialog_bg(c: str) -> bool:
        """是不是"弹窗自己的底色"（含 1 个色阶容差，避开抗锯齿边缘像素）。"""
        c = c.lower()
        if c == dlg_bg:
            return True
        try:
            r, g, b = (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16))
            dr, dg, db = (int(dlg_bg[1:3], 16), int(dlg_bg[3:5], 16),
                          int(dlg_bg[5:7], 16))
            return all(abs(a - b) == 1 for a, b in ((r, dr), (g, dg), (b, db)))
        except Exception:
            return False

    print(f"弹窗 {dlg.width()}x{dlg.height()}  截图 {W}x{H}  "
          f"has_parent={dlg.parent() is not None}")

    # ★ 坐标单位说明：GetWindowRect 在本进程（DPI-unaware）给的是**物理像素**，
    #   整屏 grabWindow 的位图也是物理像素 → 两者直接对应，不用乘 dpr。
    #   README 里那张"圆角没生效"的错觉，就是当年这里乘了两次 dpr 导致的。
    corners = {"左上": (2, 2), "右上": (W - 3, 2),
               "右下": (W - 3, H - 3), "左下": (2, H - 3)}
    corner_colors = {k: px(*v) for k, v in corners.items()}
    for k, c in corner_colors.items():
        print(f"  {k}角 = {c}")
    mid = px(W // 2, 4)
    print(f"  上边中点(4px 内) = {mid}   （对照：应在弹窗内）")
    print()

    # 判定：窗口外形被裁圆后，四角那一小块露出来的应该是**底下的窗口**（不是弹窗底色）
    still = [k for k, c in corner_colors.items() if is_dialog_bg(c)]
    if not still:
        print("[OK] 四角都不是弹窗底色 → 圆角生效")
    else:
        # 兜底：读 Win32 的区域，确认我们确实设过（避免"看起来没圆"就误判代码没跑）
        import ctypes
        import ctypes.wintypes as wt
        b = wt.RECT()
        rgn = ctypes.windll.gdi32.CreateRectRgn(0, 0, 0, 0)
        got = ctypes.windll.user32.GetWindowRgn(int(dlg.winId()), rgn)
        box = None
        if got:
            ctypes.windll.gdi32.GetRgnBox(rgn, ctypes.byref(b))
            box = (b.right, b.bottom)
        print(f"[!] {still} 取到的仍是弹窗底色；Win32 区域尺寸 = {box}，"
              f"窗口物理尺寸 = ({W},{H})")
        print("    → 若两者相等，说明区域已按整窗设置（四角只差 16px 的弧，"
              "采样点可能落在弧内）；请看图人工确认。")
    if is_dialog_bg(mid):
        print("[OK] 上边中点仍在弹窗内（说明只挖了角，没把整条边吃掉）")

    # 顺带确认区域裁剪把窗口尺寸算对了：右边/下边不该缺一条
    right_mid = px(W - 3, H // 2)
    print(f"  右边中点 = {right_mid}   （应仍是弹窗内容，不能是主窗口灰底 #eceff3 之类）")
    print("saved", out)
    app.quit()


QTimer.singleShot(900, open_dialog)
sys.exit(app.exec())
