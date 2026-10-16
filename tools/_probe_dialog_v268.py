"""v2.6.68 离屏探针：编辑弹窗布局改版。

断言：
  A1 顶栏「所属区」下拉存在（无标签）、宽度固定、值回填正确、payload 带出；
  A2 表单里**不再**出现「所属区」「图标」两个带标签行；
  A3 图标行 = 三组 [下拉+文字]，现值反推正确；
  A4 保存优先级：高铁 > 机场 > 商场；商场等级切换 payload 正确；
  A5 弹窗整窗抓图（后海 = S级红袋 + 南山区）供目检。
"""
import os
import sys

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication, QComboBox

app = QApplication.instance() or QApplication(sys.argv)

from ui.main_window import MainWindow
from ui.edit_dialog import EditDialog

win = MainWindow()
win.show()
app.processEvents()

# ---------- A1/A3/A4 后海（mall_red + 南山区）----------
d = EditDialog("后海", parent=win)
app.processEvents()

# A1 所属区
dc = d._widgets.get("district")
assert isinstance(dc, QComboBox), "A1 失败：顶栏没有所属区下拉"
assert dc.width() <= 100, f"A1 失败：所属区下拉过宽 {dc.width()}px"
assert dc.currentData() == "南山区", f"A1 失败：回填={dc.currentData()!r}"
print("[A1] 顶栏所属区下拉 OK（宽 %dpx，值=南山区）" % dc.width())

# A2 表单标签不再出现
labels = [l.text() for l in d.form_host.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)]
assert "所属区" not in labels, "A2 失败：表单仍有「所属区」标签"
assert "图标" not in labels, "A2 失败：表单仍有「图标」标签"
print("[A2] 表单无「所属区」「图标」标签 OK")

# A3 图标三组
assert d._icon_mall.currentData() == "mall_red", \
    f"A3 失败：后海应为 mall_red，实为 {d._icon_mall.currentData()!r}"
assert d._icon_hsr.currentData() == "" and d._icon_air.currentData() == ""
print("[A3] 图标三组回填 OK（后海=mall_red）")

# A4 保存优先级 + payload
p = d._collect()
assert p["icon"] == "mall_red" and p["district"] == "南山区", f"A4 失败：{p.get('icon')},{p.get('district')}"
d._icon_hsr.setCurrentIndex(d._icon_hsr.findData("hsr"))
assert d._collect()["icon"] == "hsr", "A4 失败：高铁优先级未生效"
d._icon_hsr.setCurrentIndex(0)
d._icon_mall.setCurrentIndex(d._icon_mall.findData("mall_gold"))
assert d._collect()["icon"] == "mall_gold", "A4 失败：商场等级切换未生效"
print("[A4] 保存优先级/商场等级切换 OK")

d._icon_mall.setCurrentIndex(d._icon_mall.findData("mall_red"))
d.close()
app.processEvents()

# ---------- 深圳北站（hsr）----------
d2 = EditDialog("深圳北站", parent=win)
app.processEvents()
assert d2._icon_hsr.currentData() == "hsr", "深圳北站 hsr 回填失败"
assert d2._collect()["icon"] == "hsr"
d2.close()
app.processEvents()
print("[A4b] 深圳北站 hsr 回填/保存 OK")

# ---------- A5 抓图目检（后海弹窗整窗）----------
d3 = EditDialog("后海", parent=win)
d3.show()
app.processEvents()
for _ in range(10):
    app.processEvents()
pm = d3.grab()
pm.save(r"C:/software/subway/源码/_probe_dialog_v268.png")
d3.close()
app.processEvents()
print("[A5] 弹窗抓图 -> _probe_dialog_v268.png")

win.close()
print("ALL PASS")
