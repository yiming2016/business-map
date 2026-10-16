# -*- coding: utf-8 -*-
"""检查"所属线路"展开面板自身渲染出来的背景色（确认白底+边框真的画上了）。

用法：python tools/_chk_lines_popup_bg.py
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtCore import QTimer                   # noqa: E402

from ui.widgets import LinesPopup                   # noqa: E402
from core.data_manager import get_data_manager      # noqa: E402

app = QApplication(sys.argv)
dm = get_data_manager()
pop = LinesPopup(dm.all_lines())
pop.show()


def chk():
    app.processEvents()
    pm = pop.grab()
    img = pm.toImage()
    d = pm.devicePixelRatio()
    print(f"size={pm.width()}x{pm.height()} dpr={d}")

    def px(x, y):
        return img.pixelColor(int(x * d), int(y * d)).name()

    print("左上角(1,1)        :", px(1, 1))
    print("上边内空白(200,3)  :", px(200, 3))
    print("右下内空白(w-4,h-4):", px(pop.width() - 4, pop.height() - 4))
    print("中间空白(300,150)  :", px(300, 150))

    out = SRC / "logs" / "_popup_selfgrab.png"
    pm.save(str(out))
    print("saved", out)
    app.quit()


QTimer.singleShot(500, chk)
sys.exit(app.exec())
