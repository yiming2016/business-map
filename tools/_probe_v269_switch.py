# -*- coding: utf-8 -*-
"""v2.6.9：验证「切换日期类型下拉 → 表格数据跟着变」。

用户报：「下拉菜单可以选择了，但对应的首末班车数据没改变」。

量三件事：
  ① `currentIndexChanged` 到底发的是 **int** 还是 **str**（PySide6 有重载，
     默认那一路如果选错，`_on_date_changed` 收到的就不是下标）；
  ② 切换后 `_group_boxes` 里**到底哪几个可见**（是不是一个都没变）；
  ③ 切换后**屏幕上真正能读到**的首/末班文本是不是换了（不只是看内部变量）。
"""
from __future__ import annotations

import sys, os, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLineEdit  # noqa: E402
from PySide6.QtCore import Qt                                                              # noqa: E402
from ui.timetable_editor import TimetableEditor                                            # noqa: E402

TEXT = "\n".join([
    "工作日 · 1号线：往罗湖 首06:02 末23:47；往机场东 首06:41 末23:21",
    "工作日 · 7号线：往深大丽湖 首06:30 末23:35",
    "休息日 · 1号线：往罗湖 首06:20 末23:47；往机场东 首06:55 末23:21",
    "休息日 · 7号线：往深大丽湖 首06:50 末23:35",
    "节假日 · 1号线：往罗湖 首06:35 末23:47；往机场东 首07:10 末23:21",
])

app = QApplication.instance() or QApplication(sys.argv)

win = QMainWindow()
host = QWidget()
lay = QVBoxLayout(host)
ed = TimetableEditor(TEXT)
lay.addWidget(ed)
win.setCentralWidget(host)
win.resize(900, 520)
win.show()
app.processEvents()

# ---------- ① 信号重载：发出来的是 int 还是 str ----------
_seen = []
cb = ed.date_combo
cb.currentIndexChanged.connect(lambda *a: _seen.append([type(x).__name__ for x in a]))
cb.setCurrentIndex(1)
app.processEvents()
print("[①] currentIndexChanged 实参类型 =", _seen[-1] if _seen else "(没触发)")


def snapshot():
    """当前**屏幕上**真正读得到的首/末班文本（只数可见的分组）。"""
    vis = [i for i, b in enumerate(ed._group_boxes) if b.isVisible()]
    got = []
    for i in vis:
        box = ed._group_boxes[i]
        eds = [w for w in box.findChildren(QLineEdit)]
        got.append((i, [w.text() for w in eds]))
    return vis, got


def fmt(got):
    out = []
    for i, texts in got:
        out.append("  组%d: %s" % (i, " | ".join(texts[:6])))
    return "\n".join(out)


print("\n[②][③] 依次切到每一组，看可见分组 + 屏幕上读到的文本")
for idx in range(cb.count()):
    cb.setCurrentIndex(idx)
    app.processEvents()
    vis, got = snapshot()
    print(f"\n  -- setCurrentIndex({idx})  下拉={cb.currentText()!r} "
          f"_cur={ed._cur!r} 可见组={vis}")
    print(fmt(got))

# ---------- ④ 直接调槽函数，排除"信号没连上" ----------
print("\n[④] 直接调 ed._on_date_changed(2)（绕过信号）")
ed._on_date_changed(2)
app.processEvents()
vis, got = snapshot()
print("  可见组 =", vis, " _cur =", repr(ed._cur))
print(fmt(got))

# ---------- ⑤ 变异对照：把 _on_date_changed 换成空操作 ----------
print("\n[⑤] 变异对照：把 _on_date_changed 换成空操作后再切")
ed._on_date_changed = lambda *a, **k: None
cb.setCurrentIndex(0)
app.processEvents()
vis, got = snapshot()
print("  可见组 =", vis)
print(fmt(got))
