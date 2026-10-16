# -*- coding: utf-8 -*-
"""v2.6.9：切换后，**下拉自己**有没有重绘成新文字？

`_DateCombo` 是自己画（paintEvent）的。如果切换后它没重绘，用户就会看到
"下拉还是写着『工作日』、下面表格也像没变"，从而报「数据没改变」。
判据：切换前后 `cb.grab()` 的位图**逐像素**比对 + 墨迹（前景色）像素数量。
"""
from __future__ import annotations

import sys, time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication                 # noqa: E402
from PySide6.QtGui import QColor                           # noqa: E402
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
pump(250)

dlg = EditDialog(station_id="车公庙", parent=win)
dlg.resize(760, 880)
dlg.show()
pump(600)
dlg.activateWindow()
pump(250)

tt = None
for w in dlg.findChildren(TimetableEditor):
    tt = w
cb = tt.date_combo


def ink(img, fg):
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (abs(c.red() - fg.red()) + abs(c.green() - fg.green())
                    + abs(c.blue() - fg.blue())) < 150:
                n += 1
    return n


def shot():
    pm = cb.grab()
    return pm.toImage()


def diff(a, b):
    tot = a.width() * a.height()
    n = sum(1 for y in range(a.height()) for x in range(a.width())
            if a.pixel(x, y) != b.pixel(x, y))
    return 100.0 * n / tot


shots = []
for idx in range(cb.count()):
    cb.setCurrentIndex(idx)
    pump(250)
    im = shot()
    fg = QColor(cb._fg)
    shots.append((cb.currentText(), cb._bg, im))
    print("  idx=%d 文字=%r 底色=%s 前景墨迹像素=%d"
          % (idx, cb.currentText(), cb._bg, ink(im, fg)))

print("\n[像素差异]（切换后下拉自己有没有重画）")
for i in range(len(shots) - 1):
    print("  %s → %s : %.1f%%  ⇒ %s"
          % (shots[i][0], shots[i + 1][0], diff(shots[i][2], shots[i + 1][2]),
             "重绘了" if diff(shots[i][2], shots[i + 1][2]) > 1 else "★没重绘"))

print("\n[★ 真人手势：弹窗点第2项后，下拉自己有没有重绘]")
cb.setCurrentIndex(0)
pump(250)
before = shot()
cb.setFocus()
pump(150)
cb.showPopup()
pump(400)
v = cb.view()
print("  弹窗可见 =", v.isVisible())
if v.isVisible():
    from PySide6.QtCore import Qt, QPoint                  # noqa: E402
    from PySide6.QtTest import QTest                       # noqa: E402
    idx = v.model().index(1, 0)
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier,
                     v.visualRect(idx).center())
    pump(400)
    after = shot()
    print("  点选后 currentText=%r currentIndex=%d" % (cb.currentText(),
                                                       cb.currentIndex()))
    print("  下拉位图差异 = %.1f%% ⇒ %s"
          % (diff(before, after),
             "重绘了" if diff(before, after) > 1 else "★没重绘（用户会以为没生效）"))

print("\n[DONE]")
