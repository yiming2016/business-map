# -*- coding: utf-8 -*-
"""v2.6.9：用**真人手势**（弹开列表 → 点某一项）复现「选了但数据不变」。

`setCurrentIndex()` 这条路是好的（`_probe_v269_switch*.py` 已证），
所以怀疑点集中在"通过弹窗选择"这条路上：
  · 弹窗里的点击有没有真的写回 currentIndex；
  · 以及真实弹窗尺寸（760×880）下，新显示的那组是不是**落在可视区内**
    （被滚动区裁掉的话，看上去就是"数据没变"）。
"""
from __future__ import annotations

import sys, os
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication, QLineEdit      # noqa: E402
from PySide6.QtCore import Qt, QPoint                      # noqa: E402
from PySide6.QtTest import QTest                           # noqa: E402
import PySide6.QtWidgets as QtW                            # noqa: E402

QtW.QMessageBox.warning = staticmethod(lambda *a, **k: None)
QtW.QMessageBox.information = staticmethod(lambda *a, **k: None)

from ui.edit_dialog import EditDialog                      # noqa: E402
from ui.timetable_editor import TimetableEditor            # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

dlg = EditDialog(station_id="车公庙")
dlg.resize(760, 880)          # ★ 真实弹窗尺寸
dlg.show()
app.processEvents()
app.processEvents()

tt = None
for w in dlg.findChildren(TimetableEditor):
    tt = w
cb = tt.date_combo


def show_state(tag):
    vis = [i for i, b in enumerate(tt._group_boxes) if b.isVisible()]
    print(f"  {tag}: currentIndex={cb.currentIndex()} 下拉={cb.currentText()!r} "
          f"_cur={tt._cur} 可见={vis}")
    for i in vis:
        b = tt._group_boxes[i]
        inside = tt.rect().contains(b.geometry())
        eds = b.findChildren(QLineEdit)
        print(f"      组{i} geom={b.geometry().getRect()} 在tt可视区内={inside} "
              f"首末={[w.text() for w in eds[:4]]}")
    print(f"      tt.rect={tt.rect().getRect()} sizeHint={tt.sizeHint().height()}")


print("[①] 初始")
show_state("初始")

print("\n[②] 真人手势：showPopup → 在弹窗里点第 2 项")
cb.showPopup()
app.processEvents()
v = cb.view()
print("  view 存在=%s 可见=%s  项数=%s"
      % (v is not None, v.isVisible() if v else None,
         v.model().rowCount() if v else None))
idx = v.model().index(1, 0)
v.setCurrentIndex(idx)
app.processEvents()
rect = v.visualRect(idx)
QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
app.processEvents()
app.processEvents()
cb.hidePopup()
app.processEvents()
show_state("弹窗点选后")

print("\n[③] 再点第 3 项")
cb.showPopup()
app.processEvents()
v = cb.view()
idx = v.model().index(2, 0)
v.setCurrentIndex(idx)
rect = v.visualRect(idx)
QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
app.processEvents()
cb.hidePopup()
app.processEvents()
show_state("再点第3项后")

print("\n[④] 键盘：聚焦下拉后按 ↓")
cb.setFocus()
for _ in range(2):
    QTest.keyClick(cb, Qt.Key_Down)
    app.processEvents()
show_state("按两次↓后")

print("\n[⑤] 对照：直接 setCurrentIndex(1)")
cb.setCurrentIndex(1)
app.processEvents()
show_state("setCurrentIndex(1) 后")
