"""v2.6.70 离屏探针：酒店图标 + 图标按钮选择页 + 悬浮 tooltip。

断言：
  A1 icon_pixmap 对 4 个 hotel_* 出非空位图；
  A2 后海弹窗：组0=红袋按钮（非文字"＋"），组1=红楼 + 深圳湾安达仕酒店；
  A3 _set_tag_icon 换图标（＋→红楼）+ _collect_tags payload 正确；
  A4 深圳北站 3 组（hsr/绿袋/紫楼）；
  A5 StationDotItem._tag_text_at：光标压在组0图标上返回"深圳湾万象城"，
     压在圆点中心返回空；
  A6 特写抓图。
"""
import os
import sys

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication, QToolButton
from PySide6.QtCore import QPointF

app = QApplication.instance() or QApplication(sys.argv)

from ui.metro_render import icon_pixmap

# ---------- A1 酒店位图 ----------
for k in ("hotel_red", "hotel_gold", "hotel_purple", "hotel_green"):
    pm = icon_pixmap(k, 64)
    assert pm is not None and not pm.isNull(), f"A1 失败：{k} 位图为空"
print("[A1] hotel_* 位图 4/4 OK")

from ui.main_window import MainWindow
from ui.edit_dialog import EditDialog

win = MainWindow()
win.show()
app.processEvents()

# ---------- A2/A3 后海弹窗 ----------
d = EditDialog("后海", parent=win)
app.processEvents()
b0, b1 = d._tag_btns[0], d._tag_btns[1]
assert d._tag_icons[:2] == ["mall_red", "hotel_red"], f"A2 失败：{d._tag_icons!r}"
assert b0.icon().pixmap(24).width() > 0 and b0.text() == "", "A2 失败：组0按钮没贴图"
assert d._tag_edits[1].text() == "深圳湾安达仕酒店", f"A2 失败：{d._tag_edits[1].text()!r}"
p = d._collect()
assert p["tags"] == [
    {"icon": "mall_red", "text": "深圳湾万象城", "pos": "left"},
    {"icon": "hotel_red", "text": "深圳湾安达仕酒店", "pos": "left"},
    {"icon": "mansion_red", "text": "华润深圳湾悦府（一期/二期）", "pos": "left"},
], f"A3 失败：{p.get('tags')!r}"
d._set_tag_icon(2, "hotel_gold")
d._tag_edits[2].setText("测试酒店")
out3 = d._collect()["tags"]
assert len(out3) == 3 and out3[2]["icon"] == "hotel_gold" and out3[2]["text"] == "测试酒店", \
    f"A3 失败：{out3!r}"
print("[A2] 组0红袋/组1红楼+酒店名 OK")
print("[A3] 第三组换图标+payload OK")

# ---------- A4 深圳北站 4 组（v2.6.76 加豪宅后） ----------
d.close(); app.processEvents()
d2 = EditDialog("深圳北站", parent=win)
app.processEvents()
p3 = d2._collect()["tags"]
assert [t["icon"] for t in p3] == ["hsr", "mall_green", "hotel_purple", "mansion_purple"], f"A4 失败：{p3!r}"
d2.close(); app.processEvents()
print("[A4] 深圳北站 4 组 OK")

# ---------- A5 悬浮命中 ----------
mv = win.map_view
it = mv.station_items["后海"]
it.update_from_data({"tags": [
    {"icon": "mall_red", "text": "深圳湾万象城", "pos": "left"},
    {"icon": "hotel_red", "text": "深圳湾安达仕酒店", "pos": "left"},
]})
app.processEvents()
lab = it.label
ir, _xs, _nx = lab._layout_cached()
from PySide6.QtCore import QRectF
hit = lab.mapToItem(it, QRectF(ir[0].center(), ir[0].center()).center()) if False else None
# 组0 图标中心（标签局部）→ item 坐标
c = ir[0].center()
item_pt = QPointF(lab.pos().x() + c.x() * it.label_scale(),
                  lab.pos().y() + c.y() * it.label_scale())
assert it._tag_text_at(item_pt) == "深圳湾万象城", \
    f"A5 失败：{it._tag_text_at(item_pt)!r}"
assert it._tag_text_at(QPointF(0, 0)) == "", "A5 失败：圆点中心不该命中"
print("[A5] _tag_text_at 命中/未命中 OK")

# ---------- A6 特写 ----------
mv.centerOn(QPointF(it.x(), it.y()))
mv.zoom_to_station("后海", 0.6)
for _ in range(30):
    app.processEvents()
app.processEvents()
win.grab().save(r"C:/software/subway/源码/_probe_hotel_houhai.png")
win.close()
print("[A6] 特写抓图 OK")
print("ALL PASS")
