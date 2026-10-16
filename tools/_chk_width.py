# -*- coding: utf-8 -*-
"""量「开通日期」输入框加宽后，弹窗与面板两侧是否都还塞得下。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

app = QApplication(sys.argv)
from ui.edit_dialog import EditDialog
from ui.info_panel import InfoPanel
from core.data_manager import get_data_manager

dm = get_data_manager()
sid = list(dm.all_stations().keys())[0]
d = EditDialog(station_id=sid); d.resize(600, 680); d.show()
p = InfoPanel(); p.resize(380, 800); p.show(); p.show_station(sid)

ok = True

def s():
    global ok
    for tag, obj, host in (("弹窗", d, d.form_host), ("面板", p, p.form_container)):
        box = obj._widgets["is_transfer"].parentWidget()
        le = obj._widgets["open_date"]
        fl = obj.form_layout
        m = fl.contentsMargins()
        avail = host.width() - m.left() - m.right()
        fits = box.width() <= avail
        ok = ok and fits
        print(f"{tag}: 表单可用宽 {avail} | 并排行宽 {box.width()} | "
              f"输入框宽 {le.width()} | 右边缘 {le.geometry().right()} | "
              + ("没超出 OK" if fits else f"超出 {box.width()-avail}px FAIL"))
    d.grab().save("_shot_v2418.png")
    print("\n" + ("全部通过 ✅" if ok else "存在失败 ❌"))
    app.quit()

QTimer.singleShot(900, s)
app.exec()
