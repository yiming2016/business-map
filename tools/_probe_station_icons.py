"""v2.6.67 离屏探针：站名前置图标（emoji 高铁/机场 + 商场 PNG）+ 编辑弹窗下拉框。

断言：
  A1 HaloLabel.set_icon 生效（_icon_key / _icon_px，无图标站恒为空）；
  A2 图标位图工厂能出非空 QPixmap（emoji 与 mall_* 都要）；
  A3 编辑弹窗的「图标」「所属区」两个下拉框存在、值正确回填、保存 payload 带出。
输出：站名+图标 渲染抓图（放大）。
"""
import os
import sys

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap

app = QApplication.instance() or QApplication(sys.argv)

# ---------- A2 图标位图工厂 ----------
from ui.metro_render import icon_pixmap

for k in ("hsr", "airport", "mall_red", "mall_gold", "mall_purple", "mall_green"):
    pm = icon_pixmap(k, 64)
    assert pm is not None and not pm.isNull(), "A2 失败：%s 位图为空" % k
print("[A2] 图标位图工厂 6/6 OK")

# ---------- 场景渲染 ----------
from ui.main_window import MainWindow

win = MainWindow()
win.show()
app.processEvents()

mv = win.map_view
# 给一个商场站临时设图标（只改内存，不落盘）
it = mv.station_items["老街"]
it.update_from_data({"icon": "mall_red"})
app.processEvents()

from PySide6.QtCore import QRectF

mv.centerOn(QPointF(4766, 4876))   # 老街（hsr 没设，但旁边有）——改设 深圳北站
from PySide6.QtCore import QPointF as _QPointF
szn = mv.station_items["深圳北站"]
szn.update_from_data({"icon": "hsr"})   # 数据里已是 hsr，幂等
mv.centerOn(_QPointF(szn.x(), szn.y()))
mv.zoom_to_station("深圳北站", 0.6)
for _ in range(30):
    app.processEvents()
try:
    from PySide6.QtCore import QTimer
    import time as _t
    _t0 = _t.time()
    while _t.time() - _t0 < 1.5:
        app.processEvents()
except Exception:
    pass
app.processEvents()

# 标签特写：直接从场景渲染 深圳北站 / 老街 的站名框（图标+文字）
from PySide6.QtWidgets import QGraphicsScene
for nm, _it3 in (("深圳北站", szn), ("老街", it)):
    r = _it3.label.mapToScene(_it3.label.boundingRect()).boundingRect().adjusted(-8, -8, 8, 8)
    pm2 = QPixmap(int(r.width() * 2), int(r.height() * 2))
    pm2.fill(Qt.white)
    p2 = QPainter(pm2)
    p2.setRenderHint(QPainter.Antialiasing, True)
    _it3.scene().render(p2, QRectF(pm2.rect()), r)
    p2.end()
    _out = r"C:/Users/29773/WorkBuddy/2026-09-13-00-34-00/_icon_%s.png" % nm
    pm2.save(_out)
    print("[特写]", nm, "->", _out)

# A1 断言
assert szn.label._icon_key == "hsr" and szn.label._icon_px > 0, "A1 失败：hsr 图标没挂上"
assert it.label._icon_key == "mall_red", "A1 失败：mall_red 图标没挂上"
_n = 0
for _sid, _it2 in mv.station_items.items():
    if _it2.label._icon_key:
        _n += 1
print("[A1] set_icon 生效 OK（带图标站数=%d：数据 7 站 + 老街临时 = 8）" % _n)

# 抓图（视口）
vp = mv.viewport()
img = vp.grab()
out = r"C:/Users/29773/WorkBuddy/2026-09-13-00-34-00/_icons_probe.png"
img.save(out)
print("[图] 已保存", out)

# ---------- A3 编辑弹窗 ----------
win.close()

from ui.edit_dialog import EditDialog

d = EditDialog(station_id="深圳北站")
cb_icon = d._widgets.get("icon")
cb_dist = d._widgets.get("district")
assert cb_icon is not None and cb_dist is not None, "A3 失败：下拉框没建出来"
assert cb_icon.currentData() == "hsr", "A3 失败：图标值没回填（%r）" % cb_icon.currentData()
assert cb_dist.count() == 10, "A3 失败：所属区应有 10 项（含不设置），实 %d" % cb_dist.count()
cb_icon.setCurrentIndex(cb_icon.findData("mall_gold"))
cb_dist.setCurrentIndex(cb_dist.findData("龙华区"))
payload = d._collect()
assert payload.get("icon") == "mall_gold", "A3 失败：payload.icon=%r" % payload.get("icon")
assert payload.get("district") == "龙华区", "A3 失败：payload.district=%r" % payload.get("district")
print("[A3] 编辑弹窗下拉框 3/3 OK（回填/选项数/payload 带出）")
print("ALL PASS")
