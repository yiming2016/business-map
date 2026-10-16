"""
tools/_probe_v269_combo.py
=========================
v2.6.9 下拉菜单体检：量三个数 + 一个功能验证。

1. 「工作日」到底有没有显示全：
   可用文字宽 = 下拉总宽 − combo_chrome()（箭头区×2 + 边距×2）
   vs  QFontMetrics.horizontalAdvance("工作日")
   ★ 另外验"居中"：文字相对整颗胶囊居中 ⇒ 左右空白都 ≥ 箭头区宽（不撞三角）
2. 下拉与右侧表头「线路」的距离（用户要求"挨得近一些"）
3. 点下拉能不能弹列表
   ★★ 这个环境里**任何**下拉都弹不出窗口（连普通 QComboBox 点下去也是
      view=False / activePopup=False —— 窗口没拿到前台焦点）。所以不能用
      "弹窗可见"当判据，改成**给 showPopup 装计数器**：点一下 → 计数器 +1，
      证明"点击真的走到了弹列表这一步"（v2.6.8 坏的就是这一步）。
4. 紧凑档是否仍塞得进右侧面板（可用宽 356px）

★ 别加 QT_QPA_PLATFORM=offscreen：离屏平台默认字体不同，宽度全是假数
  （项目里已经踩过三次，见 MEMORY §5.14）。
"""

import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from PySide6.QtCore import Qt, QPoint                              # noqa: E402
from PySide6.QtGui import QFont, QFontMetrics, QMouseEvent          # noqa: E402
from PySide6.QtWidgets import (                                    # noqa: E402
    QApplication, QWidget, QVBoxLayout, QLabel, QComboBox,
)
from PySide6.QtTest import QTest                                   # noqa: E402

import core.data_manager as CDM                                    # noqa: E402

_TMP = tempfile.mkdtemp(prefix="v269_")
for k in ("STATIONS_FILE", "LINES_FILE", "DATA_DIR"):
    setattr(CDM, k, os.path.join(_TMP, k.lower() + ".json") if k != "DATA_DIR" else _TMP)

from ui.timetable_editor import TimetableEditor, FONT_FAMILY       # noqa: E402

TEXT = (
    "工作日 · 1号线：往罗湖 首06:02 末23:47；往机场东 首06:41 末23:21\n"
    "工作日 · 7号线：往深大丽湖 首06:30 末23:35\n"
    "休息日 · 1号线：往罗湖 首06:12 末23:47；往机场东 首06:51 末23:21\n"
    "节假日 · 1号线：往罗湖 首06:22 末23:47；往机场东 首07:01 末23:21\n"
)


def p(*a):
    print(*a)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = QWidget()
    v = QVBoxLayout(win)

    eds = {}
    for compact in (False, True):
        ed = TimetableEditor(TEXT, compact=compact)
        v.addWidget(ed)
        eds[compact] = ed
    win.resize(900, 700)
    win.show()
    app.processEvents()

    for compact in (False, True):
        ed = eds[compact]
        cb = ed.date_combo
        m = ed._combo_metric()
        chrome = ed.combo_chrome(m)
        f = QFont(FONT_FAMILY)
        f.setPointSizeF(m["pt"])
        f.setBold(True)
        fm = QFontMetrics(f)
        names = [g.date for g in ed._groups]
        longest = max(names, key=lambda s: fm.horizontalAdvance(s))
        tw = fm.horizontalAdvance(longest)

        p("=" * 70)
        p("档位：%s" % ("紧凑(右侧面板)" if compact else "完整(编辑弹窗)"))
        p("  是否可编辑(必须否): %s" % cb.isEditable())
        p("  最长选项 / 文字宽  : %s / %.1fpx" % (longest, tw))
        p("  下拉总宽           : %dpx  (区间 %d~%d)" % (cb.width(), m["lo"], m["hi"]))
        p("  内耗 chrome        : %dpx = 箭头%d×2 + 边距%d×2"
          % (chrome, m["arrow"], m["edge"]))
        left = (cb.width() - tw) / 2.0
        p("  文字左右留白       : 各 %.1fpx  ⇒ 字显示全=%s；不撞箭头=%s"
          % (left, "是" if cb.width() - chrome >= tw else "★否",
             "是" if left >= m["arrow"] else "★否"))
        p("  下拉与表格的间距   : %dpx" % ed._combo_gap())
        # 2. 与表头「线路」的距离
        labs = [w for w in ed.findChildren(QLabel) if w.text() == "线路"]
        if labs:
            lab = labs[0]
            g = cb.mapTo(ed, QPoint(cb.width(), cb.height() // 2))
            h = lab.mapTo(ed, QPoint(0, lab.height() // 2))
            p("  下拉右缘x→线路左缘x: %d → %d   间距 %dpx" % (g.x(), h.x(), h.x() - g.x()))
        # 3. 点击是否走到 showPopup
        hits = [0]
        orig = cb.showPopup
        cb.showPopup = lambda: (hits.__setitem__(0, hits[0] + 1), orig())[1]
        QTest.mouseClick(cb, Qt.LeftButton)
        app.processEvents()
        p("  点击→showPopup 次数: %d  ⇒ %s"
          % (hits[0], "可点" if hits[0] >= 1 else "★点不动"))
        cb.showPopup = orig
        # 对照：一个普通下拉（证明"计数法"在这环境下是有效判据）
        ctl = QComboBox(win)
        ctl.addItems(["甲", "乙"])
        ctl.move(600, 10)
        ctl.resize(80, 26)
        ctl.show()
        app.processEvents()
        h2 = [0]
        o2 = ctl.showPopup
        ctl.showPopup = lambda: (h2.__setitem__(0, h2[0] + 1), o2())[1]
        QTest.mouseClick(ctl, Qt.LeftButton)
        app.processEvents()
        p("  [对照]普通下拉     : showPopup %d 次，view可见=%s"
          % (h2[0], ctl.view().isVisible()))
        ctl.hide()
        # 4. 紧凑档宽度预算
        hint = ed.sizeHint().width()
        if compact:
            p("  sizeHint().width() : %dpx  (面板可用 356 ⇒ %s)"
              % (hint, "OK" if hint <= 356 else "★溢出"))
        else:
            p("  sizeHint().width() : %dpx  (弹窗可用 ~720 ⇒ %s)"
              % (hint, "OK" if hint <= 700 else "★溢出"))

    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
