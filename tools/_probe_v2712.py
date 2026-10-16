# -*- coding: utf-8 -*-
"""v2.7.12 探针：四项改动的判据（**全程离屏，不弹任何窗口**）。

用户原话（v2.7.12）：
  ① 双击的弹窗下站点文字未居中；
  ② 右侧的弹窗下，区的下拉菜单「区」字没有完全显示出来；
  ③ 右侧的弹窗可以向左拉变得更宽，但要设置一个限度；
  ④ 主图中可上下/左右拖动，设置一个拖动限度，避免已经完全白屏了还可以拖动。
"""
import os
import sys

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtCore import Qt, QEvent, QPointF            # noqa: E402
from PySide6.QtGui import QFontMetrics, QFocusEvent        # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit      # noqa: E402
from PySide6.QtTest import QTest                           # noqa: E402

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK  ' if cond else 'FAIL'}] {name}" + (f"   （{extra}）" if extra else ""))


app = QApplication(sys.argv)
from ui.main_window import MainWindow                      # noqa: E402
from ui.edit_dialog import EditDialog, _center_until_focus  # noqa: E402
import ui.map_view as MV                                   # noqa: E402

win = MainWindow()
win.show()
panel = win.info_panel
mv = win.map_view


def pump(n=12):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


pump(12)

# ---------------------------------------------------------------- ①
print("===== ① 双击弹窗：站名默认居中，点进去编辑才靠左 =====")
ed = EditDialog("后瑞", None)
ne = ed.name_edit
ok("①-1 弹窗站名**默认居中**", ne.alignment() & Qt.AlignCenter, f"{int(ne.alignment())}")
app.sendEvent(ne, QFocusEvent(QEvent.FocusIn))
ok("①-2 获得焦点后**靠左**（光标从左往右）", ne.alignment() & Qt.AlignLeft,
   f"{int(ne.alignment())}")
app.sendEvent(ne, QFocusEvent(QEvent.FocusOut))
ok("①-3 失焦后**回到居中**", ne.alignment() & Qt.AlignCenter, f"{int(ne.alignment())}")
_ed2 = QLineEdit("临时站")
_center_until_focus(_ed2)
ok("①-4 同一套逻辑可复用于任意站名输入框", _ed2.alignment() & Qt.AlignCenter)
ed.close()

# ---------------------------------------------------------------- ②
print("===== ② 「所属区」下拉：「福田区」三个字必须完整 =====")
d = panel.top_district
fm = QFontMetrics(d.font())
txt_w = max(fm.horizontalAdvance(d.itemText(i)) for i in range(d.count()))
# 下拉控件内耗：箭头 + 左右 padding，实测 ~34px（样式表量得，留 6px 冗余按 40 算）
avail = d.width() - 40
ok("②-1 下拉宽度够放下**最长选项**", avail >= txt_w,
   f"框宽 {d.width()} − 内耗 40 = {avail}，最长文字 {txt_w}")
ok("②-2 宽度不再是被拍窄的 80", d.width() > 80, f"{d.width()}px")
ok("②-3 仍比「所属线路」下拉窄（没抢它的宽度）",
   d.width() <= panel.top_lines_select.width(),
   f"区 {d.width()} vs 线路 {panel.top_lines_select.width()}")

# ---------------------------------------------------------------- ③
print("===== ③ 右侧面板：能拖宽，但有上下限 =====")
# ★ v2.7.13：面板已从 splitter 挪成"地图之上的浮层"（不再挤地图），
#   判据跟着改成"浮层宽度由 _set_info_w + _layout_overlays 管理"。
win.resize(1600, 900)
pump(10)
if not win.info_panel.isVisible():
    win._on_toggle_info_panel()
pump(10)
wrap = win.info_wrap
cap = win._overlay_width_cap()
print(f"       （离屏窗口 {win.width()}px，浮层宽度上限 {cap}px）")
win._set_info_w(5000)
pump(6)
w_wide = wrap.width()
ok("③-1 面板有**最大宽度**（往左拖有封顶）", w_wide <= cap + 2, f"{w_wide}px")
win._set_info_w(10)
pump(6)
w_narrow = wrap.width()
ok("③-2 面板有**最小宽度**（往右拖不至于拖没）", w_narrow >= 360 - 2, f"{w_narrow}px")
win._set_info_w(520)
pump(6)
w_mid = wrap.width()
ok("③-3 仍**能拖宽**（不是被钉死），撞到上限就停", 360 < w_mid <= cap + 2,
   f"{w_mid}px（下限 360 / 上限 {cap}）")
ok("③-4 面板宽度变化**不影响地图宽度**（浮层覆盖，不挤地图）",
   abs(mv.width() - win.map_area.width()) <= 2,
   f"map {mv.width()} / area {win.map_area.width()}")
ok("③-5 两侧都有拖宽把手（替代原来的分栏拖动条）",
   getattr(win, "legend_grip", None) is not None and getattr(win, "info_grip", None) is not None)


# ===== ④（原"主图拖动"）已由 v2.7.13 的 tools/_probe_v2713.py 圈2 接管：
#      判据从"视口中心 + 0.25 视口"升级成"视口四边贴住所有元素最外边界"，
#      旧常量 PAN_OVERSCROLL 已删除，这里不再重复测。
print(f"\n===== 结果：{len(PASS)} 通过 / {len(FAIL)} 失败 =====")
if FAIL:
    for f in FAIL:
        print("  FAIL:", f)
sys.exit(1 if FAIL else 0)
