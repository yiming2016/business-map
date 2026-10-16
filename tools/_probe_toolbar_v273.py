# -*- coding: utf-8 -*-
"""
★ 已过时（v2.7.16 标记）：本探针测的是 **v2.7.3 的工具栏结构**
（搜索/定位 在最前、编辑模式在其后）。v2.7.13/2.7.14 两轮改过之后：
  · 三栏 splitter 已删除（面板改浮层）；
  · 编辑按钮整体挪到模式按钮**左侧**，模式按钮文字 = 目标模式；
  · 工具栏里混进了普通 QAction（模式按钮 / ⚙️），不再全是 QWidgetAction。
⇒ T1/T2 的"第 N 个控件是谁"已不成立。
   · 按钮排布/模式切换 ⇒ 看 `tools/_probe_v2714.py`
   · 「新建站点」开关（原 T3 的添加模式）⇒ 看 `tools/_probe_v2716.py` ①
这里保留原文件备查，跑的时候直接跳过（退出码 0，不算回归失败）。
"""
import sys
print("[skip] _probe_toolbar_v273 已过时（v2.7.14 改了工具栏结构），跳过；"
      "替代见 _probe_v2714 / _probe_v2716")
sys.exit(0)

"""v2.6.73 离屏探针：工具栏编辑模式开关 + 搜索前置。

断言：
  T1 工具栏里「🔍 搜索框 / 定位」排在最前（前三个元素），其后才是「编辑模式」；
  T2 默认：10 个编辑类动作全部隐藏；「编辑模式/适配窗口/100%/原图对照/关于/全屏」可见；
  T3 点开「编辑模式」→ 10 个全可见；再点 → 全隐藏；退出编辑模式顺手关掉添加模式；
  T4 抓两个状态的工具栏截图。
"""
import os
import sys

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication, QToolBar, QLineEdit, QPushButton
from PySide6.QtCore import QRect

app = QApplication.instance() or QApplication(sys.argv)

from ui.main_window import MainWindow

win = MainWindow()
win.show()
app.processEvents()

tb = win.findChildren(QToolBar)[0]
acts = tb.actions()

# ---------- T1 顺序：搜索/定位 最前，编辑模式在其后 ----------
def widget_of(i):
    # ★ v2.7.16：工具栏里现在混着普通 QAction（模式按钮 / ⚙️），只有
    #   QWidgetAction 才有 defaultWidget() —— 直接调会 AttributeError。
    from PySide6.QtWidgets import QWidgetAction
    wa = acts[i]
    return wa.defaultWidget() if isinstance(wa, QWidgetAction) else None

w0, w1, w2 = widget_of(0), widget_of(1), widget_of(2)
from PySide6.QtWidgets import QLabel
assert isinstance(w0, QLabel), f"T1 失败：第0个不是🔍标签而是 {w0!r}"
assert isinstance(w1, QLineEdit), f"T1 失败：第1个不是搜索框而是 {w1!r}"
assert isinstance(w2, QPushButton) and w2.text() == "定位", f"T1 失败：第2个不是定位按钮"
# ★ v2.7.14 起按钮文字 = 目标模式（编辑态显示「🖼 看图模式」），按"模式"匹配
edit_mode_acts = [a for a in acts if a.text().endswith("模式") and "编辑" in a.text()
                  or a.text().endswith("模式") and "看图" in a.text()]
assert len(edit_mode_acts) == 1, f"T1 失败：编辑模式按钮数量 {len(edit_mode_acts)}"
# 编辑模式应出现在「定位」按钮（索引2）之后、第一个可见 QAction 组里
assert acts.index(edit_mode_acts[0]) > 2, "T1 失败：编辑模式不在定位之后"
print("[T1] 搜索+定位最前、编辑模式紧随 OK")

# ---------- T2 默认隐藏 ----------
names = [a.text() for a in win._edit_actions]
assert len(win._edit_actions) == 10, f"T2 失败：受控动作数 {len(win._edit_actions)}"
assert all(not a.isVisible() for a in win._edit_actions), "T2 失败：默认没全藏"
print(f"[T2] 默认 10 个全隐藏 OK -> {names}")

# ---------- T3 开关 ----------
win.act_edit_mode.trigger()
app.processEvents()
assert all(a.isVisible() for a in win._edit_actions), "T3 失败：打开后没全显"
win.grab().copy(QRect(0, 0, win.width(), 72)).save(
    r"C:/software/subway/源码/_probe_toolbar_on.png")

win.act_new_station.setChecked(True)                 # 开着添加模式时退出编辑模式
win.act_edit_mode.trigger()
app.processEvents()
assert all(not a.isVisible() for a in win._edit_actions), "T3 失败：关闭后没全藏"
assert not win.act_new_station.isChecked(), "T3 失败：退出编辑模式应顺手关掉添加模式"
win.grab().copy(QRect(0, 0, win.width(), 72)).save(
    r"C:/software/subway/源码/_probe_toolbar_off.png")
print("[T3] 开/关切换 + 顺手关添加模式 OK")

# ---------- T5 v2.6.77：适配窗口/100%/关于/全屏 按钮已删 + 状态栏整行已删 ----------
from PySide6.QtWidgets import QStatusBar
tb_names = [a.text() for a in acts if a.text()]
for gone in ("⤢ 适配窗口", "100%", "❓ 关于", "⛶ 全屏 (F11)"):
    assert gone not in tb_names, f"T5 失败：{gone} 还在工具栏"
assert win.findChildren(QStatusBar) == [], "T5 失败：底部状态栏还在"
print("[T5] 适配窗口/100%/关于/全屏 按钮已删 + 状态栏整行已删 OK")

win.close()
print("ALL PASS")
