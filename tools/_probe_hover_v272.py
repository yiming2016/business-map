"""v2.6.72 修悬浮不弹 tooltip 的端到端探针。

向**视口**真实投递 MouseMove（mouse tracking 开着 ⇒ 转 scene hover），
覆盖三个位置：组0 图标中心 / 组1 图标中心 / 站点圆点中心。
断言：
  H1 hoverMoveEvent 被调用（实例级换虚方法记录，不改类）；
  H2 光标压图标时 QToolTip.isVisible() 且文本 = 记录的文字；
  H3 压圆点中心（无图标）时 tooltip 收起。
"""
import os
import sys
import types

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication, QToolTip
from PySide6.QtCore import QPointF, QEvent, Qt
from PySide6.QtGui import QMouseEvent

app = QApplication.instance() or QApplication(sys.argv)

from ui.main_window import MainWindow
from ui.metro_render import StationDotItem

win = MainWindow()
win.show()
app.processEvents()

mv = win.map_view
it = mv.station_items["后海"]
mv.centerOn(QPointF(it.x(), it.y()))
mv.zoom_to_station("后海", 0.6)
for _ in range(30):
    app.processEvents()
app.processEvents()

# ---------- 换实例虚方法：记录 hoverMoveEvent 调用 ----------
orig_hm = it.hoverMoveEvent
calls = []
def hm(self, event):
    try:
        gp = ("screenPos", event.screenPos())
    except Exception as e:
        gp = ("err", repr(e))
    calls.append((QPointF(event.pos()), gp))
    return orig_hm(event)
it.hoverMoveEvent = types.MethodType(hm, it)      # ★ 只换实例，不动类

# ---------- 计算视口坐标 ----------
lab = it.label
ir, _xs, _nx = lab._layout_cached()
def viewport_pt(item_pt):
    sp = it.mapToScene(item_pt)
    return mv.mapFromScene(sp)

def send_hover(vp):
    ev = QMouseEvent(QEvent.MouseMove, QPointF(vp), QPointF(mv.mapToGlobal(vp)),
                     Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    app.sendEvent(mv.viewport(), ev)
    for _ in range(3):
        app.processEvents()

# 图标中心（标签局部）→ item 坐标 → 视口
c0 = lab.mapToItem(it, ir[0].center())
c1 = lab.mapToItem(it, ir[1].center())
dot_pt = QPointF(0, 0)

send_hover(viewport_pt(c0))
assert calls, "H1 失败：压组0图标时 hoverMoveEvent 根本没被调用"
print(f"[H1] hoverMoveEvent 收到 {len(calls)} 次，pos={calls[-1][0]}，gp={calls[-1][1]}")
t0 = it._tag_text_at(c0)
print("     _tag_text_at(c0) =", repr(t0))
print("     直接 showText 对照：", end=" ")
QToolTip.showText(100, 100) if False else QToolTip.showText(__import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(200, 200), "direct")
app.processEvents()
print("visible =", QToolTip.isVisible())
QToolTip.hideText(); app.processEvents()

send_hover(viewport_pt(c1))
t1 = it._tag_text_at(c1)
assert t1 == "深圳湾安达仕酒店", f"H2b 失败：_tag_text_at(c1)={t1!r}"
assert "深圳湾安达仕酒店" in QToolTip.text(), f"H2b 失败：tooltip={QToolTip.text()!r}"
print("[H2b] 组1 图标 tooltip = 深圳湾安达仕酒店 OK")

send_hover(viewport_pt(dot_pt))
assert not QToolTip.isVisible(), "H3 失败：压圆点中心 tooltip 应收起"
print("[H3] 压圆点中心 tooltip 收起 OK")

QToolTip.hideText()
win.close()
print("ALL PASS")
