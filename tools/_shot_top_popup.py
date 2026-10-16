"""截一张"顶栏下拉展开"的图，肉眼确认面板位置正常。"""
import sys
from pathlib import Path
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from ui.edit_dialog import EditDialog

app = QApplication(sys.argv)
dlg = EditDialog(station_id="机场东")
dlg.resize(560, 420)
dlg.show()
for _ in range(8): app.processEvents()
dlg.lines_select._toggle_popup()
for _ in range(6): app.processEvents()
out = SRC / "logs" / "_top_popup_v2413.png"
def shot():
    scr = app.primaryScreen()
    pm = scr.grabWindow(0)
    full = pm.toImage()
    # 只截弹窗附近一大块（含展开的面板）
    tl = dlg.mapToGlobal(dlg.rect().topLeft())
    dpr = pm.width() / scr.geometry().width()
    x, y = int(tl.x()*dpr)-20, int(tl.y()*dpr)-20
    w, h = int(760*dpr), int(560*dpr)
    full.copy(x, y, w, h).save(str(out))
    print(f"[OK] {out}")
    app.quit()
QTimer.singleShot(400, shot)
app.exec()
