# -*- coding: utf-8 -*-
"""探针：在**真实的 MainWindow** 里，候选面板弹出后焦点到底去哪了。

独立小窗口里 focusWidget 一直是搜索框；真 App 里却变成 None。
本探针把真 App 的每一步拆开，看是哪一步把焦点弄没的。
"""
import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QInputMethodEvent            # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402

from ui.main_window import MainWindow                   # noqa: E402


def pump(n=6):
    for _ in range(n):
        QApplication.processEvents()


def brief(w):
    if w is None:
        return "None"
    n = type(w).__name__
    obj = w.objectName() if hasattr(w, "objectName") else ""
    return f"{n}:{obj}" if obj else n


def hwnd_of(w):
    try:
        return int(w.winId())
    except Exception:
        return 0


def native(tag):
    u = ctypes.windll.user32
    fg = u.GetForegroundWindow()
    fo = u.GetFocus()
    print(f"    {tag:<34} Win32 前台={fg} 键盘焦点={fo}")


def state(tag):
    app = QApplication.instance()
    print(f"  {tag}")
    print(f"    focusWidget={brief(app.focusWidget()):<26}"
          f" focusObject={brief(app.focusObject()):<26}")
    print(f"    focusWindow={brief(app.focusWindow()):<26}"
          f" activeWindow={brief(app.activeWindow()):<26}")
    print(f"    activePopup={brief(app.activePopupWidget()):<26}"
          f" topLevel={brief(app.topLevelWidgets()[0]) if app.topLevelWidgets() else '-'}")


def type_text(widget, text):
    ev = QInputMethodEvent()
    ev.setCommitString(text)
    QApplication.sendEvent(widget, ev)
    pump()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(20)
    box = win.search_box
    pop = win.search_popup
    print(f"主窗口 hwnd={hwnd_of(win)}  搜索框 hwnd={hwnd_of(box)}  "
          f"面板 hwnd={hwnd_of(pop)}")
    native("初始：")

    box.setFocus()
    pump(8)
    state("① 搜索框刚拿到焦点：")
    native("① 搜索框刚拿到焦点：")

    # 拆步：先只 setText（不弹面板）→ 看是不是 show() 干的
    pop.hide()
    pump(4)
    box.setText("园")
    pump(4)
    state("② setText('园') 之后（面板会被自动弹出）：")
    native("② setText('园') 之后：")

    pop.hide()
    pump(6)
    state("③ 手动 hide() 面板之后：")
    native("③ 手动 hide() 面板之后：")

    # 只 show 面板，什么都不做
    pop.move(win.x() + 400, win.y() + 120)
    pop.show()
    pump(8)
    state("④ 只 show() 面板（不动词）：")
    native("④ 只 show() 面板：")

    pop.raise_()
    pump(8)
    state("⑤ 再 raise_()：")

    pop.hide()
    box.setFocus()
    pump(8)
    state("⑥ hide + setFocus 复原：")

    # 真 App 的真实流程：焦点在搜索框 → 提交一个汉字
    type_text(box, "山")
    state("⑦ 提交汉字（真实流程，面板弹出了）：")
    native("⑦ 提交汉字：")

    print(f"\n  面板可见={pop.isVisible()}  可见行数={len(pop.visible_rows())}")
    print(f"  搜索框文本={box.text()!r}")

    win.close()
    pump(6)
    return 0


if __name__ == "__main__":
    sys.exit(main())
