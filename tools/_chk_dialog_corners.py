# -*- coding: utf-8 -*-
"""专门验证"独立弹窗的四角真的被裁圆了"。

做法：把弹窗放到一块纯色背景上（先铺一个纯色矩形窗口），截屏后看四角像素
是不是**背景色**（= 被挖掉了）而中心是弹窗底色。
只靠 dlg.grab() 是看不出来的 —— 那只画控件自己，不反映窗口外形。

用法：python tools/_chk_dialog_corners.py
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtCore import Qt, QTimer, QRect                    # noqa: E402
from PySide6.QtGui import QColor                                # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget             # noqa: E402

from ui.edit_dialog import EditDialog                           # noqa: E402

app = QApplication(sys.argv)


class Backdrop(QWidget):
    """一块纯色底板，用来当"桌面"，颜色选个弹窗里绝不会出现的品红。"""

    BG = "#ff00ff"

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setStyleSheet(f"background:{self.BG};")
        self.show()


back = Backdrop()
back.setGeometry(0, 0, 1600, 1200)   # 铺满，保证弹窗四角周围都是底板而不是真桌面
dlg = EditDialog("车公庙")
dlg.resize(560, 700)
dlg.move(200, 200)          # 落在底板内部，四角周围都是"桌面"
dlg.show()
dlg.raise_()
back.raise_()               # 底板提到最前
dlg.raise_()                # 再让弹窗压在底板之上


def probe():
    app.processEvents()
    QTimer.singleShot(600, real)


def real():
    app.processEvents()
    scr = QApplication.primaryScreen()
    full = scr.grabWindow(0)
    dpr = full.devicePixelRatio() or 1.0
    tl = dlg.mapToGlobal(QRect(0, 0, 1, 1).topLeft())
    pm = full.copy(int(tl.x() * dpr), int(tl.y() * dpr),
                   int(dlg.width() * dpr), int(dlg.height() * dpr))
    out = SRC / "logs" / "_dialog_corners.png"
    pm.save(str(out))

    img = pm.toImage()
    W, H = img.width(), img.height()

    def px(x, y):
        return img.pixelColor(x, y).name()

    print(f"截图 {W}x{H}（逻辑 {dlg.width()}x{dlg.height()}）")
    print(f"背景(底板)色 = {Backdrop.BG}   弹窗底色 = #f7f8fa")
    # 只看"紧贴窗口边缘的那一圈"（圆角就在这一圈里），
    # 中心/边上这些位置会被子控件盖住，取到 #ffffff 是正常的，不参与判断。
    corners = {
        "左上角": (3, 3),
        "右上角": (W - 4, 3),
        "右下角": (W - 4, H - 4),
        "左下角": (3, H - 4),
    }
    cut = 0
    for name, (x, y) in corners.items():
        c = px(x, y)
        is_bg = c.lower() == Backdrop.BG.lower()
        cut += int(is_bg)
        print(f"  {name:6s} ({x:4d},{y:4d}) = {c}   {'← 已挖空' if is_bg else '← 仍是窗口内容'}")
    # 对照：边中点应该在窗口内（说明只有角被挖，边没被吃掉）
    edge = px(W // 2, 2)
    print(f"  上边中点 ({W // 2},{2}) = {edge}   （应在窗口内，不是背景色）")

    print()
    if cut == 4:
        print("[OK] 四个角全部是背景色 → 窗口外形被裁成了圆角矩形")
    elif cut >= 2:
        print(f"[~] {cut}/4 个角被挖空（可能圆角半径偏小，看图确认）")
    else:
        print("[!!] 四角都不是背景色 → 圆角没生效，窗口还是直角矩形")
    print("saved", out)
    app.quit()


QTimer.singleShot(900, probe)
sys.exit(app.exec())
