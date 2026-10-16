# -*- coding: utf-8 -*-
"""v2.6.9：右侧信息面板（compact 档）里切换日期类型，看数据变不变。

用户只说"下拉菜单"，没说是弹窗还是右侧面板 —— 两边都要量。
面板这边多一个风险：`show_station()` 每次都**重建** TimetableEditor，
如果切换之后被任何一次重建打断，`_cur` 会被打回 0（表现就是"选了又跳回去"）。
"""
from __future__ import annotations

import sys, os
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication, QLineEdit      # noqa: E402
import PySide6.QtWidgets as QtW                            # noqa: E402

QtW.QMessageBox.warning = staticmethod(lambda *a, **k: None)

from ui.info_panel import InfoPanel                        # noqa: E402
from ui.timetable_editor import TimetableEditor            # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

p = InfoPanel()
p.resize(380, 800)
p.show()
p.show_station("车公庙")
app.processEvents()
app.processEvents()

tt = None
for w in p.findChildren(TimetableEditor):
    tt = w
if tt is None:
    print("面板里没找到 TimetableEditor")
    sys.exit(1)

cb = tt.date_combo
print("下拉项:", [cb.itemText(i) for i in range(cb.count())],
      " 紧凑=", tt.compact, " 宽=", cb.width())


def state(tag):
    vis = [i for i, b in enumerate(tt._group_boxes) if b.isVisible()]
    txt = []
    for i in vis:
        eds = tt._group_boxes[i].findChildren(QLineEdit)
        txt.append(" | ".join(w.text() for w in eds[:6]))
    print(f"  {tag}: idx={cb.currentIndex()} {cb.currentText()!r} _cur={tt._cur} "
          f"可见={vis} → {txt}")


state("初始")
for idx in range(cb.count()):
    cb.setCurrentIndex(idx)
    app.processEvents()
    state(f"切到{idx}")

# 关键：切完之后再触发一次面板刷新，看 _cur 会不会被打回 0
print("\n[★] 切到 2 之后再 show_station 一次同站（模拟面板刷新）")
cb.setCurrentIndex(2)
app.processEvents()
state("切到2后")
p.show_station("车公庙")
app.processEvents()
tt2 = None
for w in p.findChildren(TimetableEditor):
    tt2 = w
print("  重建后是同一个实例吗:", tt2 is tt)
cb = tt2.date_combo
vis = [i for i, b in enumerate(tt2._group_boxes) if b.isVisible()]
print("  刷新后: idx=%d %r 可见=%s" % (cb.currentIndex(), cb.currentText(), vis))
