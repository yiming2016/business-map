# -*- coding: utf-8 -*-
"""判断"屏幕截图(QScreen.grabWindow)"是否可信：
   把弹窗上某个已知点的颜色，跟屏幕截图里同一点的像素对比。

   · 一致  -> 屏幕截图可信，之前看到面板是灰底就说明面板真的没画白底
   · 不一致 -> 屏幕截图在这个环境下不可信（高DPI / 合成窗口），看 grab() 为准
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtCore import QTimer, QPoint           # noqa: E402

from ui.edit_dialog import EditDialog               # noqa: E402

app = QApplication(sys.argv)
dlg = EditDialog(station_id="机场东")
dlg.show()


def probe():
    dlg.raise_()
    dlg.activateWindow()
    app.processEvents()
    QTimer.singleShot(400, real)


def real():
    app.processEvents()

    # 弹窗自己 render 出来的图（基准）
    own = dlg.grab()
    d = own.devicePixelRatio() or 1.0
    own_img = own.toImage()

    # 弹窗标题栏下方的一个点：表单区的灰色背景
    pt = QPoint(int(dlg.width() * 0.5), 40)          # 逻辑坐标（弹窗内）
    own_c = own_img.pixelColor(int(pt.x() * d), int(pt.y() * d)).name()

    # 屏幕截图里的同一点
    scr = QApplication.primaryScreen()
    full = scr.grabWindow(0)
    fd = full.devicePixelRatio() or 1.0
    g = dlg.mapToGlobal(pt)
    screen_c = full.toImage().pixelColor(int(g.x() * fd), int(g.y() * fd)).name()

    print(f"弹窗逻辑尺寸 {dlg.width()}x{dlg.height()}  dlg.dpr={d}  screen.dpr={fd}")
    print(f"弹窗内逻辑点 {pt.x()},{pt.y()}")
    print(f"  render 取色 : {own_c}")
    print(f"  screen 取色 : {screen_c}")
    print("=> 屏幕截图" + ("可信" if own_c == screen_c else "不可信（要看 grab/render）"))
    app.quit()


QTimer.singleShot(700, probe)
sys.exit(app.exec())
