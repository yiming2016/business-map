# -*- coding: utf-8 -*-
"""
视觉自查：把搜索候选面板真的画出来存图，让人眼看一遍。

为什么要单独存图：功能断言全绿 ≠ 长得对。
弹层是独立顶层窗口，样式表写错一点就会变成"白底白字"或"透明底板"，
这类问题只有看图才能发现（本项目 HoverTip 就栽过一次：只有样式表没 paintEvent，
提示框实际是全透明的，浅色文字基本看不清）。

输出：
  _shot_search_popup_bar.png    整条工具栏 + 面板（含屏幕真实像素，验系统合成）
  _shot_search_popup_card.png   面板本体的清晰大图（widget.grab，验样式/字号）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

OUT = ROOT / "_shots"


def pump(n=8):
    for _ in range(n):
        QApplication.processEvents()


def feed(widget, text):
    ev = QInputMethodEvent()
    ev.setCommitString(text)
    QApplication.sendEvent(widget, ev)
    pump()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    win.activateWindow()
    pump(20)
    win.search_box.setFocus()
    pump()

    OUT.mkdir(exist_ok=True)
    shots = []

    for tag, text in (("a_园", "园"), ("b_机场", "机场"), ("c_无匹配", "zzz")):
        win.search_box.clear()
        pump(3)
        feed(win.search_box, text)
        pop = win.search_popup
        if not pop.isVisible():
            print(f"[跳过] {tag} 面板没出现")
            continue

        # 1) 面板本体清晰图
        card = OUT / f"_shot_search_popup_card_{tag}.png"
        pop.grab().save(str(card))
        shots.append(card)

        # 2) 屏幕真实像素（含系统合成效果）：从搜索框上下各截一块
        scr = QApplication.primaryScreen()
        box = win.search_box
        x0 = max(0, box.mapToGlobal(QPoint(0, 0)).x() - 120)
        y0 = max(0, box.mapToGlobal(QPoint(0, 0)).y() - 40)
        w = 520
        h = 340
        pm = scr.grabWindow(0, x0, y0, w, h)
        bar = OUT / f"_shot_search_popup_bar_{tag}.png"
        pm.save(str(bar))
        shots.append(bar)
        print(f"[存图] {tag}: 面板 {pop.width()}x{pop.height()}  行数={len(pop.visible_rows())}  "
              f"note={pop.note_text()!r}  → {card.name} / {bar.name}")

    win.search_popup.hide()
    print("\n产出：")
    for s in shots:
        print("  ", s)


if __name__ == "__main__":
    main()
