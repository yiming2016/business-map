"""v2.6.75 探针：图标可见性开关面板 + 悬浮图标不弹站点气泡。

  P1 IconTogglePanel 存在、4 个类别按钮、默认全开；
  P2 左键关"商场"类 → 后海标签里 mall_red 消失、hotel_red 还在；开回来恢复；
  P3 等级级开关：关 hotel_red → 后海红楼消失；开回来恢复；
  P4 豪宅占位位图：icon_pixmap("mansion_*", 48) 非空；
  P5 悬浮图标（组0 红袋中心）→ 站点气泡 HoverTip 不显示；悬站点圆点 → 显示；
  P6 状态落盘：view_settings.json 出现 icon_visibility（测完恢复原状）。
"""
import json
import os
import sys

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import QPointF

app = QApplication.instance() or QApplication(sys.argv)

from ui.main_window import MainWindow
from ui.metro_render import icon_pixmap, ICON_CATEGORIES

win = MainWindow()
win.show()
app.processEvents()

mv = win.map_view
it = mv.station_items["后海"]
lab = it.label

# ---------- P1 ----------
panel = mv.icon_panel
btns = [b for b in panel.findChildren(QPushButton)]
assert len(btns) == 4, f"P1 失败：类别按钮数 {len(btns)}"
assert all(b.isChecked() for b in btns), "P1 失败：默认应全开"
names = [b.text() for b in btns]
print(f"[P1] 面板 4 类别按钮默认全开 OK -> {names}")

# ---------- P2 类别开关 ----------
base_tags = [t[0] for t in lab._tags]
assert "mall_red" in base_tags and "hotel_red" in base_tags, f"P2 前提失败：{base_tags}"
mall_btn = btns[0]
mall_btn.setChecked(True)
mall_btn.click()                                 # 左键 = 整类开关（→ 关）
app.processEvents()
new_tags = [t[0] for t in lab._tags]
assert "mall_red" not in new_tags, f"P2 失败：商场类关掉后仍在 {new_tags}"
assert "hotel_red" in new_tags, "P2 失败：酒店类不该受影响"
mall_btn.setChecked(False)
mall_btn.click()                                 # 再点一次（→ 开）
app.processEvents()
new_tags = [t[0] for t in lab._tags]
assert "mall_red" in new_tags, "P2 失败：重开后商场没恢复"
print("[P2] 类别左键开关（商场关/开，酒店不受影响）OK")

# ---------- P3 等级开关 ----------
panel._toggle_level("hotel_red")
app.processEvents()
new_tags = [t[0] for t in lab._tags]
assert "hotel_red" not in new_tags, f"P3 失败：红楼关掉后仍在 {new_tags}"
panel._toggle_level("hotel_red")
app.processEvents()
new_tags = [t[0] for t in lab._tags]
assert "hotel_red" in new_tags, "P3 失败：红楼没恢复"
print("[P3] 等级右键级开关（hotel_red 关/开）OK")

# ---------- P4 豪宅占位位图 ----------
for k in ("mansion_red", "mansion_gold", "mansion_purple", "mansion_green"):
    pm = icon_pixmap(k, 48)
    assert pm is not None and not pm.isNull(), f"P4 失败：{k} 占位位图为空"
print("[P4] 豪宅四色占位位图 4/4 OK")

# ---------- P5 悬浮图标不弹站点气泡 ----------
vs_file = mv.view_settings_file()
bak = None
if os.path.exists(vs_file):
    bak = open(vs_file, "r", encoding="utf-8").read()

mv.centerOn(QPointF(it.x(), it.y()))
mv.zoom_to_station("后海", 0.6)
for _ in range(30):
    app.processEvents()
app.processEvents()

lab = it.label
ir, _xs, _nx = lab._layout_cached()
c0_item = lab.mapToItem(it, ir[0].center())       # 组0 红袋中心（item 坐标）
vp_c0 = mv.mapFromScene(it.mapToScene(c0_item))
vp_dot = mv.mapFromScene(it.mapToScene(QPointF(0, 0)))

win._handle_hover(vp_c0)
assert not win.tip.isVisible(), "P5 失败：悬浮图标时站点气泡弹出来了"
print("[P5a] 悬浮图标 → 站点气泡不显示 OK")

win._handle_hover(vp_dot)
assert win.tip.isVisible(), "P5 失败：悬浮站点圆点时气泡应显示"
win.tip.hide()
print("[P5b] 悬浮站点圆点 → 站点气泡显示 OK")

# ---------- P6 落盘 ----------
assert os.path.exists(vs_file), "P6 失败：view_settings.json 不存在"
d = json.load(open(vs_file, encoding="utf-8"))
assert "icon_visibility" in d, f"P6 失败：没有 icon_visibility 键 {list(d)}"
print(f"[P6] icon_visibility 落盘 OK -> {d['icon_visibility']}")

# 恢复现场（探针写的是源码侧 view_settings.json）
if bak is not None:
    open(vs_file, "w", encoding="utf-8").write(bak)
else:
    os.remove(vs_file)
win.close()
print("ALL PASS")
