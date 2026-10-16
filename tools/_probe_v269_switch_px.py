# -*- coding: utf-8 -*-
"""v2.6.9：把「切换下拉后数据没变」拆成两种可能，用像素判定。

可能 A：**画面没重绘**（内部状态变了，屏上还是旧的）→ 前后两张位图几乎一样。
可能 B：**三组数据本来就长得一样** → 位图确实变了，但人眼看不出差别
        （真实数据里很多站三种日期类型的时间相同或只差几分钟）。

判据：
  · 切 0→1 后 `tt.grab()` 的像素差异率
  · 「去掉日期类型文字后，三组内容是否逐字相同」的站点占比
"""
from __future__ import annotations

import sys, os
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication, QLineEdit      # noqa: E402
import PySide6.QtWidgets as QtW                            # noqa: E402

QtW.QMessageBox.warning = staticmethod(lambda *a, **k: None)
QtW.QMessageBox.information = staticmethod(lambda *a, **k: None)

from core.data_manager import get_data_manager             # noqa: E402
from ui.edit_dialog import EditDialog                      # noqa: E402
from ui.timetable_editor import TimetableEditor            # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
dm = get_data_manager()

# ================= ① 真实数据：三种日期类型内容是否雷同 =================
def bodies(tt: str):
    """按日期类型分段，返回 [(日期, [去掉日期前缀后的正文...]), ...]"""
    out = []
    cur = None
    for ln in str(tt or "").splitlines():
        ln = ln.strip()
        if not ln or "·" not in ln:
            continue
        d, rest = ln.split("·", 1)
        d, rest = d.strip(), rest.strip()
        if cur is None or cur[0] != d:
            cur = (d, [])
            out.append(cur)
        cur[1].append(rest)
    return out


same = 0
multi = 0
examples = []
for sid, st in dm.all_stations().items():
    bs = bodies(st.get("timetable"))
    if len(bs) < 2:
        continue
    multi += 1
    if len({tuple(v) for _, v in bs}) == 1:
        same += 1
        if len(examples) < 6:
            examples.append((sid, bs[0][1][:2]))
print("[①] 有 ≥2 种日期类型的站：%d；三组内容**逐字相同**的：%d (%.1f%%)"
      % (multi, same, 100.0 * same / max(1, multi)))
for sid, b in examples:
    print("     雷同样例:", sid, b[0][:60])

# ================= ② 像素：切换后画面到底变没变 =================
print("\n[②] 真实弹窗里切档，比对像素")
dlg = EditDialog(station_id="车公庙")
dlg.show()
app.processEvents()

tt = None
for w in dlg.findChildren(TimetableEditor):
    tt = w
print("  下拉项:", [tt.date_combo.itemText(i) for i in range(tt.date_combo.count())])


def grab():
    pm = tt.grab()
    return pm.toImage(), pm


def diff(a, b):
    if a.size() != b.size():
        return None
    n = 0
    tot = a.width() * a.height()
    for y in range(0, a.height(), 2):
        for x in range(0, a.width(), 2):
            if a.pixel(x, y) != b.pixel(x, y):
                n += 1
    return 100.0 * n / (len(range(0, a.height(), 2)) * len(range(0, a.width(), 2)))


imgs = []
for idx in range(tt.date_combo.count()):
    tt.date_combo.setCurrentIndex(idx)
    app.processEvents()
    app.processEvents()
    im, pm = grab()
    imgs.append(im)
    print("  idx=%d %s  尺寸=%s" % (idx, tt.date_combo.currentText(), pm.size()))

for i in range(len(imgs) - 1):
    d = diff(imgs[i], imgs[i + 1])
    print("  %d→%d 像素差异率 = %s  ⇒ %s"
          % (i, i + 1, ("%.1f%%" % d) if d is not None else "尺寸不同",
             "画面变了" if (d or 0) > 0.5 else "★画面几乎没变"))

# ================= ③ 排除"内部变了但没重绘"：直接看屏上文本 =================
print("\n[③] 屏上真正读得到的首/末班（每行前 6 个输入框）")
for idx in range(tt.date_combo.count()):
    tt.date_combo.setCurrentIndex(idx)
    app.processEvents()
    vis = [i for i, b in enumerate(tt._group_boxes) if b.isVisible()]
    for i in vis:
        eds = tt._group_boxes[i].findChildren(QLineEdit)
        print("  %s → %s" % (tt.date_combo.currentText(),
                             " | ".join(w.text() for w in eds[:12])))
