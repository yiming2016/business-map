"""v2.6.71 离屏探针：编辑页图标悬浮 tooltip 显示含义原文。

断言：
  T1 _icon_tooltip：红楼 = 短名 + "S级·顶奢奢华" 原文；金楼=A级；紫楼=B级；绿楼=C级；
     商场四色各含"购物中心/综合商场/中型/社区"字样；hsr/airport 有释义；空值短名。
  T2 后海弹窗：组0 按钮 tooltip 含"商场一级"+"城市顶级购物中心"；
     组1 按钮 tooltip 含"酒店一级"+"顶奢奢华：国际顶级奢华品牌"。
  T3 选择页网格：逐个构造 QToolButton 不好断言（exec 阻塞），改为直接断言
     _icon_tooltip 对 ICON_CATALOG 全量非空且已知图标含含义行。
"""
import os
import sys

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from ui.edit_dialog import _icon_tooltip, ICON_CATALOG, ICON_MEANINGS

# ---------- T1 纯函数 ----------
t = _icon_tooltip("hotel_red")
assert "红楼·酒店一级" in t and "S级·顶奢奢华" in t and "城市地标级旗舰物业" in t, f"T1 失败: {t!r}"
assert "A级·豪华五星" in _icon_tooltip("hotel_gold")
assert "B级·标准五星" in _icon_tooltip("hotel_purple")
assert "C级·高端准五星" in _icon_tooltip("hotel_green")
assert "城市顶级购物中心" in _icon_tooltip("mall_red")
assert "区域核心综合商场" in _icon_tooltip("mall_gold")
assert "片区中型购物中心" in _icon_tooltip("mall_purple")
assert "社区便民" in _icon_tooltip("mall_green")
assert "高铁站" in _icon_tooltip("hsr") and "机场" in _icon_tooltip("airport")
assert _icon_tooltip("") == "无", f"T1 失败: {_icon_tooltip('')!r}"
print("[T1] _icon_tooltip 10/10 OK")

# ---------- T2 弹窗按钮 tooltip ----------
from ui.main_window import MainWindow
from ui.edit_dialog import EditDialog

win = MainWindow()
win.show()
app.processEvents()

d = EditDialog("后海", parent=win)
app.processEvents()
tip0 = d._tag_btns[0].toolTip()
tip1 = d._tag_btns[1].toolTip()
assert "商场一级" in tip0 and "城市顶级购物中心" in tip0, f"T2 失败: {tip0!r}"
assert "酒店一级" in tip1 and "顶奢奢华" in tip1 and "国际顶级奢华品牌" in tip1, f"T2 失败: {tip1!r}"
print("[T2] 按钮 tooltip 含含义原文 OK")

# ---------- T3 目录全覆盖 ----------
for v, lab in ICON_CATALOG:
    tt = _icon_tooltip(v)
    assert tt and lab.split(" ")[0] in tt, f"T3 失败: {v!r} -> {tt!r}"
    if v in ICON_MEANINGS:
        assert "\n" in tt, f"T3 失败（缺含义行）: {v!r}"
print("[T3] ICON_CATALOG 全覆盖 OK")
d.close(); win.close()
print("ALL PASS")
