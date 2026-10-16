"""v2.6.69 离屏探针：图标标签（多组 [下拉+⚙️+文字]）+ 地图标签渲染。

断言：
  A1 后海弹窗：组0 = mall_red + 文字"深圳湾万象城"；payload 带出 tags 列表；
  A2 ⚙️ 位置切换（left→top）进 payload；
  A3 深圳北站 = 两组（hsr + mall_green 缤果空间）回填/保存；
  A4 机场(T3) = airport + "宝安机场"；
  A5 HaloLabel.set_tags 排版：文字路径含标签文字、图标矩形一一对应；
  A6 地图标签特写抓图（后海 / 深圳北站 / top 位置演示）。
"""
import os
import sys

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QToolButton

app = QApplication.instance() or QApplication(sys.argv)

from ui.main_window import MainWindow
from ui.edit_dialog import EditDialog

win = MainWindow()
win.show()
app.processEvents()

# ---------- A1 后海 ----------
d = EditDialog("后海", parent=win)
app.processEvents()
c0, e0 = d._tag_combos[0], d._tag_edits[0]
assert c0.currentData() == "mall_red", f"A1 失败：组0={c0.currentData()!r}"
assert e0.text() == "深圳湾万象城", f"A1 失败：文字={e0.text()!r}"
assert isinstance(d._tag_gears[0], QToolButton) and d._tag_gears[0].width() <= 26
p = d._collect()
assert p["tags"] == [{"icon": "mall_red", "text": "深圳湾万象城", "pos": "left"}], \
    f"A1 失败：payload={p.get('tags')!r}"
print("[A1] 后海 组0=mall_red+深圳湾万象城，payload OK")

# ---------- A2 ⚙️ 位置 ----------
d._set_tag_pos(0, "top")
assert d._collect()["tags"][0]["pos"] == "top", "A2 失败：pos=top 未进 payload"
d._set_tag_pos(0, "left")
# 组1：选机场 + 输文字
d._tag_combos[1].setCurrentIndex(d._tag_combos[1].findData("airport"))
d._tag_edits[1].setText("宝安机场")
p2 = d._collect()["tags"]
assert len(p2) == 2 and p2[1] == {"icon": "airport", "text": "宝安机场", "pos": "left"}, \
    f"A2 失败：{p2!r}"
print("[A2] ⚙️ 位置/第二组 OK")

# ---------- A3 深圳北站 双组 ----------
d.close(); app.processEvents()
d2 = EditDialog("深圳北站", parent=win)
app.processEvents()
p3 = d2._collect()["tags"]
assert len(p3) == 2 and p3[0]["icon"] == "hsr" and p3[1]["text"] == "缤果空间", \
    f"A3 失败：{p3!r}"
d2.close(); app.processEvents()
print("[A3] 深圳北站 双组（hsr + 绿袋·缤果空间）OK")

# ---------- A4 机场(T3) ----------
d4 = EditDialog("机场(T3)", parent=win)
app.processEvents()
p4 = d4._collect()["tags"]
assert p4 == [{"icon": "airport", "text": "宝安机场", "pos": "left"}], f"A4 失败：{p4!r}"
d4.close(); app.processEvents()
print("[A4] 机场(T3) = ✈️宝安机场 OK")

# ---------- A5 渲染层排版 ----------
from PySide6.QtCore import QPointF
mv = win.map_view
it = mv.station_items["后海"]
it.update_from_data({"tags": [{"icon": "mall_red", "text": "深圳湾万象城", "pos": "left"}]})
app.processEvents()
lab = it.label
path = lab._text_path()
assert path.boundingRect().width() > 0
assert len(lab._tags) == 1 and not lab._layout_cached()[0][0].isNull()
print("[A5] set_tags 排版 OK")

# ---------- A6 特写抓图 ----------
from ui.metro_render import icon_pixmap
mv.centerOn(QPointF(it.x(), it.y()))
mv.zoom_to_station("后海", 0.6)
for _ in range(30):
    app.processEvents()
app.processEvents()
win.grab().save(r"C:/software/subway/源码/_probe_tags_houhai.png")

szn = mv.station_items["深圳北站"]
mv.centerOn(QPointF(szn.x(), szn.y()))
mv.zoom_to_station("深圳北站", 0.6)
for _ in range(30):
    app.processEvents()
app.processEvents()
win.grab().save(r"C:/software/subway/源码/_probe_tags_szbn.png")

# top 位置演示（内存改，不落盘）
it.update_from_data({"tags": [{"icon": "mall_red", "text": "深圳湾万象城", "pos": "top"}]})
mv.centerOn(QPointF(it.x(), it.y()))
for _ in range(20):
    app.processEvents()
win.grab().save(r"C:/software/subway/源码/_probe_tags_top.png")
it.update_from_data({"tags": [{"icon": "mall_red", "text": "深圳湾万象城", "pos": "left"}]})
win.close()
print("[A6] 特写抓图 3 张 OK")
print("ALL PASS")
