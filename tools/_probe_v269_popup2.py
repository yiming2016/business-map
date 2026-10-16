# -*- coding: utf-8 -*-
"""v2.6.9：让窗口**真正激活**后再试弹窗点选（`_probe_v269_popup.py` 里没激活，
`view.isVisible()=False` ⇒ 那条路根本没走到，测了等于没测）。

拿到"弹窗真的显示"之后，再在弹窗里点第 2 项，看 `currentIndex` 有没有写回。
"""
from __future__ import annotations

import sys, time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication, QLineEdit      # noqa: E402
from PySide6.QtCore import Qt                              # noqa: E402
from PySide6.QtTest import QTest                           # noqa: E402
import PySide6.QtWidgets as QtW                            # noqa: E402

QtW.QMessageBox.warning = staticmethod(lambda *a, **k: None)

from ui.main_window import MainWindow                      # noqa: E402
from ui.edit_dialog import EditDialog                      # noqa: E402
from ui.timetable_editor import TimetableEditor            # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)


def pump(ms=250):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)


win = MainWindow()
win.resize(1480, 900)
win.show()
pump(700)
win.activateWindow()
pump(300)
print("activeWindow =", type(QApplication.activeWindow()).__name__)

dlg = EditDialog(station_id="车公庙", parent=win)
dlg.resize(760, 880)
dlg.show()
pump(600)
dlg.activateWindow()
pump(300)
print("activeWindow(弹窗后) =", type(QApplication.activeWindow()).__name__)

tt = None
for w in dlg.findChildren(TimetableEditor):
    tt = w
cb = tt.date_combo


def state(tag):
    vis = [i for i, b in enumerate(tt._group_boxes) if b.isVisible()]
    txt = []
    for i in vis:
        eds = tt._group_boxes[i].findChildren(QLineEdit)
        txt.append(" | ".join(w.text() for w in eds[:4]))
    print(f"  {tag:<18} idx={cb.currentIndex()} {cb.currentText()!r} "
          f"可见={vis} {txt}")


state("初始")

print("\n[★] showPopup（窗口已激活）")
cb.setFocus()
pump(150)
cb.showPopup()
pump(400)
v = cb.view()
print("  view.isVisible() =", v.isVisible(),
      " activePopup =", type(QApplication.activePopupWidget()).__name__)

if not v.isVisible():
    print("  ⇒ 本环境仍然弹不出，改用 view.window() 强制 show()")
    try:
        v.window().show()
        v.window().raise_()
        pump(400)
        print("  强制后 view.isVisible() =", v.isVisible())
    except Exception as e:
        print("  强制失败:", e)

if v.isVisible():
    idx = v.model().index(1, 0)
    r = v.visualRect(idx)
    print("  点第2项 rect =", r.getRect())
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, r.center())
    pump(400)
    state("弹窗点第2项后")
    idx = v.model().index(2, 0)
    r = v.visualRect(idx)
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, r.center())
    pump(400)
    state("弹窗点第3项后")
else:
    print("  ⇒ 无法在本环境复现弹窗点选，改判据：`activated` 信号（Qt 只在")
    print("     用户真的从列表里选了一项时才发）+ 键盘上下键。")
    hits = []
    cb.activated.connect(lambda i: hits.append(("activated", i)))
    cb.currentIndexChanged.connect(lambda i: hits.append(("idxChanged", i)))
    cb.setCurrentIndex(1)
    pump(200)
    print("  setCurrentIndex(1) 触发:", hits)
    state("setCurrentIndex(1) 后")
    cb.setFocus()
    QTest.keyClick(cb, Qt.Key_Down)
    pump(200)
    print("  按↓后触发:", hits)
    state("按↓后")

print("\n[DONE]")
