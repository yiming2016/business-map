"""
假设：`所属线路` 的下拉是 Qt.Popup 窗口 —— Qt 规定 Popup 会**独占键盘输入**。
若它被创建/显示后没正常释放，键盘输入就进不到输入框 → "输入文字没反应"。

验证：
  1. 反复切换站点（每次都会新建一个 LinesSelect + 新的 LinesPopup），
     检查 QApplication.activePopupWidget() 是否残留；
  2. 检查 focusWidget 是否还在我们期望的输入框上；
  3. 真敲字，确认文字有没有落进框里。
"""
from __future__ import annotations
import sys, time
from pathlib import Path
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit

app = QApplication(sys.argv)
from core.data_manager import get_data_manager
from ui.main_window import MainWindow
from ui.edit_dialog import EditDialog
from ui.widgets import LinesPopup, LinesSelect

def p(*a):
    print(*a, flush=True)

def pump(ms=200):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)

def state(tag):
    aw = QApplication.activeWindow()
    pw = QApplication.activePopupWidget()
    mw = QApplication.activeModalWidget()
    fw = QApplication.focusWidget()
    fwn = type(fw).__name__ if fw is not None else "None"
    p(f"  {tag:<32} activeWindow={type(aw).__name__ if aw else 'None':<16} "
      f"popup={type(pw).__name__ if pw else 'None':<14} "
      f"modal={type(mw).__name__ if mw else 'None':<10} focus={fwn}")

dm = get_data_manager()
sids = list(dm.all_stations().keys())

p("=" * 110)
p("① 反复切换站点（每次都重建面板 → 新建 LinesSelect/LinesPopup）")
p("=" * 110)
win = MainWindow(); win.resize(1480, 900); win.show(); pump(700)
for i in range(6):
    win._on_station_clicked(sids[i])
    pump(250)
    state(f"第{i+1}次切换站点后")

p()
p("  面板里现存的 LinesPopup 个数 =",
  len(win.info_panel.findChildren(LinesPopup)))
p("  面板里现存的 LinesSelect 个数 =",
  len(win.info_panel.findChildren(LinesSelect)))

p()
p("=" * 110)
p("② 点开下拉再关掉，看 popup 是否正常释放")
p("=" * 110)
ls = win.info_panel._widgets.get("lines")
p(f"  lines 控件类型 = {type(ls).__name__}")
if isinstance(ls, LinesSelect):
    ls._toggle_popup()
    pump(200)
    state("展开下拉后")
    p(f"    popup.isVisible() = {ls._popup.isVisible()}")
    ls._toggle_popup()
    pump(200)
    state("再点一次收起后")
    p(f"    popup.isVisible() = {ls._popup.isVisible()}")
    # 模拟"点外面关掉"
    ls._toggle_popup(); pump(150)
    ls._popup.hide(); pump(150)
    state("手动 hide 后")

p()
p("=" * 110)
p("③ ★ 关键：面板里真敲字，看能不能落进框里")
p("=" * 110)
w = win.info_panel._widgets.get("station_name")
w.setFocus(); pump(150)
state("点到名称框后")
p(f"    hasFocus = {w.hasFocus()}   文本 = {w.text()!r}")
before = w.text()
win.info_panel.activateWindow(); pump(100)
# 直接给焦点控件发按键（等价于真实键盘）
for ch in "abc":
    ev = QKeyEvent(QKeyEvent.KeyPress, 0, Qt.NoModifier, ch)
    app.sendEvent(QApplication.focusWidget(), ev)
pump(200)
p(f"    发键 'abc' 后 → 文本 = {w.text()!r}   （原 {before!r}）")
p(f"    ⚠️ 若文本没变，说明按键被别的东西（popup/modal）吃掉了")

p()
p("=" * 110)
p("④ 弹窗里同样试一遍")
p("=" * 110)
dlg = EditDialog(station_id=sids[0], parent=win)
dlg.show(); pump(600)
dw = dlg._widgets.get("station_name")
dw.setFocus(); pump(150)
state("弹窗名称框聚焦后")
for ch in "xy":
    ev = QKeyEvent(QKeyEvent.KeyPress, 0, Qt.NoModifier, ch)
    app.sendEvent(QApplication.focusWidget(), ev)
pump(200)
p(f"    发键 'xy' 后 → 文本 = {dw.text()!r}  hasFocus={dw.hasFocus()}")
p(f"    弹窗里的 LinesPopup 个数 = {len(dlg.findChildren(LinesPopup))}")
p(f"    activePopupWidget = {QApplication.activePopupWidget()}")

dlg.close(); win.close()
print("[DONE]")
