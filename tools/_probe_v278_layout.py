# -*- coding: utf-8 -*-
"""v2.6.78 探针：①缩放/图标面板嵌入工具栏「原图对照」右侧且一行；
②信息面板改版（宽度1.5×、无按钮条、无线路/ID副标题、顶部站名输入框、
无「站点名称」行、无「简介」标签）。"""
import os
import sys

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import (
    QApplication, QToolBar, QToolButton, QLineEdit, QStatusBar,
)

app = QApplication.instance() or QApplication(sys.argv)

from ui.main_window import MainWindow  # noqa: E402
from ui.scale_panel import ScalePanel  # noqa: E402
from ui.icon_toggle_panel import IconTogglePanel  # noqa: E402

win = MainWindow()
win.show()
for _ in range(15):
    app.processEvents()

# ---------- T1：两个面板在工具栏里、位于「原图对照」右侧、同一行 ----------
tb = win.findChildren(QToolBar)[0]
acts = tb.actions()
names = [(a.text(), tb.widgetForAction(a)) for a in acts]
under_idx = next(i for i, (t, _w) in enumerate(names) if t == "🖼 原图对照")
w_scale = names[under_idx + 2][1]   # +1 是分隔条
w_icon = names[under_idx + 3][1]
assert isinstance(w_scale, ScalePanel), f"T1 失败：原图对照右侧不是缩放面板而是 {w_scale!r}"
assert isinstance(w_icon, IconTogglePanel), f"T1 失败：第二个不是图标面板而是 {w_icon!r}"
# 同一行：工具栏高度 < 90px（两行会 >100）
assert tb.height() < 90, f"T1 失败：工具栏高度 {tb.height()}px，疑似折成两行"
print(f"[T1] 面板已嵌入工具栏原图对照右侧，工具栏高 {tb.height()}px（单行）OK")

# ---------- T2：视口里不再有这两个浮层 ----------
assert win.map_view.scale_panel.parent() is not win.map_view.viewport(), \
    "T2 失败：缩放面板还挂在视口上"
assert win.map_view.icon_panel.parent() is not win.map_view.viewport(), \
    "T2 失败：图标面板还挂在视口上"
print("[T2] 两面板已脱离视口浮层 OK")

# ---------- T3：状态栏仍不存在 ----------
assert win.findChildren(QStatusBar) == [], "T3 失败：状态栏又回来了"
print("[T3] 底部仍无状态栏 OK")

# ---------- T4：信息面板改版 ----------
ip = win.info_panel
ip.show_station("后海")
for _ in range(10):
    app.processEvents()

assert isinstance(ip.title, QLineEdit), f"T4 失败：顶部不是输入框而是 {ip.title!r}"
assert ip.title.text() == "后海", f"T4 失败：顶部输入框={ip.title.text()!r}"
assert not ip.subtitle.isVisible(), "T4 失败：线路/ID 副标题仍可见"
for b in (ip.btn_save, ip.btn_cancel, ip.btn_more, ip.btn_delete):
    assert not b.isVisible(), f"T4 失败：按钮 {b.text()} 仍可见"
# 表单里没有「站点名称」「简介」标签行
labels = [l.text() for l in ip.findChildren(type(ip.subtitle).__mro__[-1])
          if hasattr(l, "text")]
from PySide6.QtWidgets import QLabel  # noqa: E402
labels = [l.text() for l in ip.findChildren(QLabel)]
assert "站点名称" not in labels, f"T4 失败：表单里还有「站点名称」{labels}"
assert "简介" not in labels, f"T4 失败：表单里还有「简介」{labels}"
# 宽度 1.5×（320→480 / 460→690）
assert ip.minimumWidth() == 480 and ip.maximumWidth() == 690, \
    f"T4 失败：面板宽度 {ip.minimumWidth()}~{ip.maximumWidth()}"
# 站名输入框参与收集（改字能进 payload）
ip.title.setText("后海X")
payload = ip._collect()
assert payload.get("station_name") == "后海X", f"T4 失败：collect 站名={payload.get('station_name')!r}"
ip.title.setText("后海")
print("[T4] 顶部站名输入框/无副标题/无按钮条/无站点名称行/无简介标签/宽度1.5× OK")

# ---------- T5：截图 ----------
win.grab().save(r"C:/software/subway/源码/_probe_v278_layout.png")
win.close()
print("ALL PASS")
