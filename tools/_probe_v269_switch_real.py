# -*- coding: utf-8 -*-
"""v2.6.9：在**真实编辑弹窗**里复现「切换下拉 → 数据不变」。

独立造的 TimetableEditor 是好的（`_probe_v269_switch.py` 三档全对），
所以问题一定出在真实弹窗这条路上。这里量：
  ① 真实数据里每个站到底有几种日期类型（有没有重复/交错）；
  ② 真实弹窗里切下标后，可见分组 + 屏幕读到的文本变没变；
  ③ 顺带看看组合是不是被"重建"了（重建会换掉 date_combo 实例）。
"""
from __future__ import annotations

import sys, os
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication, QLineEdit      # noqa: E402
import PySide6.QtWidgets as QtW                            # noqa: E402

# 拦截模态框（真实弹框会阻塞）
QtW.QMessageBox.warning = staticmethod(lambda *a, **k: None)
QtW.QMessageBox.information = staticmethod(lambda *a, **k: None)

from core.data_manager import get_data_manager             # noqa: E402
from ui.edit_dialog import EditDialog                      # noqa: E402
from ui.timetable_editor import TimetableEditor            # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
dm = get_data_manager()

# ---------- ① 真实数据里日期类型的分布 ----------
from collections import Counter
cnt = Counter()
picks = []
for sid, st in dm.all_stations().items():
    tt = str(st.get("timetable") or "")
    dates = []
    for ln in tt.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        d = ln.split("·")[0].strip() if "·" in ln else "?"
        if not dates or dates[-1] != d:
            dates.append(d)
    cnt[len(dates)] += 1
    if len(dates) >= 3 and len(picks) < 4:
        picks.append((sid, dates))
print("[①] 每站的日期类型段数分布：", dict(sorted(cnt.items())))
print("    样例（段数≥3 的站）：")
for sid, ds in picks:
    print("      ", sid, ds)

target = picks[0][0] if picks else None
print("\n[②] 打开真实弹窗 station_id=%r" % target)
if target is None:
    sys.exit(0)

dlg = EditDialog(station_id=target)
dlg.show()
app.processEvents()

tt = None
for w in dlg.findChildren(TimetableEditor):
    tt = w
    break
if tt is None:
    print("  没找到 TimetableEditor")
    sys.exit(1)

cb = tt.date_combo
print("  下拉项数 =", cb.count(), " →", [cb.itemText(i) for i in range(cb.count())])
print("  分组数   =", len(tt._group_boxes))


def snap():
    vis = [i for i, b in enumerate(tt._group_boxes) if b.isVisible()]
    lines = []
    for i in vis:
        eds = [w for w in tt._group_boxes[i].findChildren(QLineEdit)]
        lines.append("组%d(%s): %s" % (i, tt._groups[i].date,
                                       " | ".join(w.text() for w in eds[:6])))
    return vis, lines


for idx in range(cb.count()):
    before_id = id(tt.date_combo)
    cb.setCurrentIndex(idx)
    app.processEvents()
    vis, lines = snap()
    print("\n  -- idx=%d 下拉=%r _cur=%r 可见=%s combo实例换了=%s"
          % (idx, tt.date_combo.currentText(), tt._cur, vis,
             id(tt.date_combo) != before_id))
    for ln in lines:
        print("     ", ln)

# ---------- ③ 用鼠标真点一次（走完整事件链） ----------
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
print("\n[③] 用 QTest 真点下拉中心（走完整事件链）")
cb = tt.date_combo
QTest.mouseClick(cb, Qt.LeftButton)
app.processEvents()
print("  当前下拉 =", cb.currentText(), " _cur =", tt._cur,
      " 可见 =", [i for i, b in enumerate(tt._group_boxes) if b.isVisible()])
