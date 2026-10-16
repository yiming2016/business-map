# -*- coding: utf-8 -*-
"""v2.4.16 截图：换乘站/开通日期并排行 + 保存按钮光标。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer

app = QApplication(sys.argv)
from ui.edit_dialog import EditDialog
from core.data_manager import get_data_manager

dm = get_data_manager()
sid = list(dm.all_stations().keys())[0]
dlg = EditDialog(station_id=sid)
dlg.resize(600, 680)
dlg.show()

def shot():
    dlg.grab().save("_shot_v2416_dialog.png")
    print("saved _shot_v2416_dialog.png", dlg.btn_save.cursor().shape())
    # 保存按钮的悬停矩形（用于人工核对光标区域）
    r = dlg.btn_save.rect()
    print("save btn rect:", r.getRect(), "enabled:", dlg.btn_save.isEnabled())
    app.quit()

QTimer.singleShot(700, shot)
app.exec()
