# -*- coding: utf-8 -*-
"""探针：Qt.Popup 一弹出来就抢走了搜索框的 Qt 焦点，怎么才能不抢？

只回答一个问题（其余都是打印，不做判断）：
  弹层显示时 `QApplication.focusWidget()` / `focusObject()` 到底是谁？
  加 WA_ShowWithoutActivating / WindowDoesNotAcceptFocus / setFocusProxy
  能不能把焦点留在搜索框？留在搜索框之后，窗口级按键还进不进搜索框？

★ 为什么在意：焦点一旦离开搜索框，
    · 搜索框的光标会消失（用户看到"输入被取消了"）；
    · 输入法（IME）的焦点对象变成 None，中文可能组不进字。
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QLineEdit, QMainWindow, QLabel

sys.path.insert(0, r"C:\software\subway\源码")


def pump(n=5):
    for _ in range(n):
        QApplication.processEvents()


def brief(w):
    if w is None:
        return "None"
    return type(w).__name__ + (f":{w.objectName()}" if w.objectName() else "")


def state(tag):
    app = QApplication.instance()
    ap = app.activePopupWidget()
    print(f"    {tag:<28} focusWidget={brief(app.focusWidget()):<18}"
          f" focusObject={brief(app.focusObject()):<18}"
          f" activePopup={brief(ap):<18}"
          f" 弹层可见={bool(ap)}")
    return app.focusWidget()


class Win(QMainWindow):
    def __init__(self, name, setup):
        super().__init__()
        self.setWindowTitle(name)
        self.resize(500, 300)
        self.box = QLineEdit(self)
        self.box.setObjectName("Box")
        self.setCentralWidget(self.box)
        self.pop = QFrame(self, Qt.Popup)
        self.pop.setObjectName("Pop")
        self.pop.setFixedSize(200, 60)
        lbl = QLabel("候选", self.pop)
        lbl.setFocusPolicy(Qt.NoFocus)
        lbl.move(8, 8)
        for w in self.pop.findChildren(object):
            pass
        setup(self.pop, self.box)


def v_none(pop, box):
    pass


def v_noactivate(pop, box):
    pop.setAttribute(Qt.WA_ShowWithoutActivating)


def v_nofocus(pop, box):
    pop.setWindowFlags(pop.windowFlags() | Qt.WindowDoesNotAcceptFocus)


def v_proxy(pop, box):
    pop.setFocusPolicy(Qt.StrongFocus)
    pop.setFocusProxy(box)


def v_tool(pop, box):
    pop.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                       | Qt.WindowDoesNotAcceptFocus
                       | Qt.WindowStaysOnTopHint)
    pop.setAttribute(Qt.WA_ShowWithoutActivating)


VARIANTS = [
    ("① 现在的写法（纯 Qt.Popup）", v_none),
    ("② + WA_ShowWithoutActivating", v_noactivate),
    ("③ + WindowDoesNotAcceptFocus", v_nofocus),
    ("④ + setFocusProxy(搜索框)", v_proxy),
    ("⑤ 改成 Tool 窗口（不用 Popup）", v_tool),
]


def run(name, setup):
    print(f"\n===== {name} =====")
    win = Win(name, setup)
    win.show()
    win.box.setFocus()
    pump(8)
    state("弹层还没弹：")
    win.pop.move(win.x() + 60, win.y() + 160)
    win.pop.show()
    pump(8)
    got = state("弹层弹出来了：")

    # 窗口级按键（走真实分发路径）
    win.box.setText("")
    pump(4)
    QTest.keyClick(win.windowHandle(), Qt.Key_B)
    pump(6)
    print(f"    窗口级敲 'b' → 搜索框内容={win.box.text()!r}"
          f"   {'✓ 进得去' if win.box.text() == 'b' else '✗ 丢了'}")

    # 输入法目标
    app = QApplication.instance()
    print(f"    输入法焦点对象 IS box？ {app.focusObject() is win.box}"
          f"   （None 表示中文组字可能进不来）")

    # 弹层是否会自动关（Popup 特性）
    win.pop.hide()
    pump(4)
    win.box.setText("")
    win.close()
    pump(6)
    return got


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    print("=" * 90)
    print("Qt.Popup 抢焦点 —— 5 种写法对照（窗口级按键 = 走真实分发路径）")
    print("=" * 90)
    for name, setup in VARIANTS:
        run(name, setup)
    print("\n" + "=" * 90)
    print("结论：看哪一行的 focusWidget 仍是 QLineEdit:Box，且窗口级按键进得去。")
    print("=" * 90)
    return 0


if __name__ == "__main__":
    sys.exit(main())
