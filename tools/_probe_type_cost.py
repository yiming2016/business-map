# -*- coding: utf-8 -*-
"""探针：搜索框每敲一个字的那十几毫秒，具体花在哪。

怀疑对象：候选卡片是**顶层窗口**，内容变少时 `_apply_size()` 会改它的高度
→ 每次都是一次原生窗口 resize（SetWindowPos）+ 重绘。
本探针把它拆开量：处理器 / 填面板 / 改高度 / 原生 resize / 重绘，各占多少。
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QInputMethodEvent                 # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

from ui.main_window import MainWindow                       # noqa: E402


def pump(n=2):
    for _ in range(n):
        QApplication.processEvents()


def drain():
    for _ in range(80):
        QApplication.processEvents()
    time.sleep(0.30)
    for _ in range(20):
        QApplication.processEvents()


def t(fn, n=1):
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) * 1000.0 / n


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    win.activateWindow()
    pump(10)
    box = win.search_box
    pop = win.search_popup
    box.setFocus()
    pump(6)
    drain()

    QS = ("园", "园山", "园山西")
    print("=" * 88)
    print("逐字打「园 → 园山 → 园山西」时的各项耗时（ms）")
    print("=" * 88)

    # 0) 基线：搜索框自己（面板关着）
    box.textChanged.disconnect(win._on_search_text_changed)
    base = []
    for q in QS:
        box.clear()
        pump(2)
        t0 = time.perf_counter()
        ev = QInputMethodEvent()
        ev.setCommitString(q)
        QApplication.sendEvent(box, ev)
        pump(2)
        base.append((time.perf_counter() - t0) * 1000.0)
    box.textChanged.connect(win._on_search_text_changed)
    print(f"0) 搜索框自己（面板关着）      " + "  ".join(f"{q}={v:.1f}" for q, v in zip(QS, base)))

    # 1) 只跑处理器（筛选 + 填面板 + 量尺寸，不含重绘）
    h = []
    for q in QS:
        h.append(t(lambda q=q: win._on_search_text_changed(q), 1))
    print(f"1) 只跑处理器（不 processEvents）" + "  ".join(f"{q}={v:.2f}" for q, v in zip(QS, h)))

    # 2) 处理器 + pump(2)  ← 这就是"整条链路"
    full = []
    for q in QS:
        box.clear()
        pump(2)

        def once(q=q):
            ev = QInputMethodEvent()
            ev.setCommitString(q)
            QApplication.sendEvent(box, ev)
            pump(2)

        full.append(t(once, 3))
    print(f"2) 整条链路（处理器 + 重绘）    " + "  ".join(f"{q}={v:.1f}" for q, v in zip(QS, full)))

    # 3) 纯原生 resize：只改候选卡片高度，一个字都不填
    box.clear()
    pump(2)
    win._on_search_text_changed("园")
    pump(4)
    print(f"\n   面板当前 {pop.width()}x{pop.height()}  可见行数={len(pop.visible_rows())}")
    hh = pop.height()

    def grow():
        pop.setFixedHeight(hh + 10)
        pump(2)

    def same():
        pop.setFixedHeight(hh)
        pump(2)

    print(f"3) 顶层窗口改高度(+10px)        {t(grow, 3):.2f}   ← 原生 resize + 重绘")
    print(f"   顶层窗口设成同一个高度        {t(same, 3):.2f}   ← 高度没变时的开销")
    pop.setFixedHeight(hh)
    pump(2)

    # 4) 只重绘（不改变任何尺寸）
    print(f"4) 只 repaint 一次             {t(lambda: (pop.update(), pump(2)), 3):.2f}")

    # 5) 滚区 show/hide（0 行时要藏它）
    def toggle():
        pop.area().setVisible(False)
        pop.area().setVisible(True)
        pump(2)

    print(f"5) 滚区 hide+show 一轮          {t(toggle, 3):.2f}")

    # 6) 拆分：填面板 & 量尺寸 各自
    box.clear()
    pump(2)
    print(f"\n6) set_items(24 行) 单独         "
          f"{t(lambda: pop.set_items([(str(i), '站' + str(i), '1号线') for i in range(24)], 24), 5):.2f}")
    print(f"   _apply_size() 单独            {t(pop._apply_size, 20):.2f}")

    pop.hide()
    win.close()
    pump(4)
    print("\n提示：`_apply_size` 只有在**行数变化**时才真的改高度；行数没变时看第 3 行第二项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
