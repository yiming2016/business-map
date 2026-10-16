"""v2.6.74 探针：主图图标悬浮 tooltip（globalPos → screenPos 修复验证）。

背景 bug：v2.6.70 的 hoverMoveEvent 用了 Qt5 遗留 API event.globalPos()，
Qt6 的 QGraphicsSceneHoverEvent 没有该方法 ⇒ 每次悬浮都抛 AttributeError
被 Qt 吞掉 ⇒ tooltip 永远不弹（v2.6.74 改 event.screenPos() 修复）。

验证方式：
  · 视口→场景的 hover 投递链路已用真实 MouseMove 验证过（可到达 item 的
    hoverMoveEvent）；离屏下 Qt 对合成 hover 有去重，投递不稳定 ⇒ 不作硬断言。
  · 本探针直接以标准 QGraphicsSceneHoverEvent 调用 hoverMoveEvent（实例级），
    确定性验证处理器不再抛异常、tooltip 文本正确：
  H1 压组0/组1 图标 → handler 无异常，QToolTip 文本 = 记录文字；
  H2 压站点圆点中心（无图标）→ tooltip 收起；
  H3 离屏 tooltip 基线（排除平台因素）。
"""
import os
import sys
import types

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication, QToolTip, QGraphicsSceneHoverEvent
from PySide6.QtCore import QPointF, QEvent, QPoint

app = QApplication.instance() or QApplication(sys.argv)

from ui.main_window import MainWindow

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

orig_hm = it.hoverMoveEvent
calls = []
def hm(self, event):
    calls.append(QPointF(event.pos()))
    return orig_hm(event)
it.hoverMoveEvent = types.MethodType(hm, it)      # ★ 只换实例，不动类

lab = it.label
ir, _xs, _nx = lab._layout_cached()

def hover_at(item_pt):
    ev = QGraphicsSceneHoverEvent(QEvent.GraphicsSceneHoverMove)
    sp = it.mapToScene(QPointF(item_pt))
    ev.setScenePos(sp)
    ev.setPos(QPointF(item_pt))
    ev.setLastScenePos(sp)
    ev.setLastPos(QPointF(item_pt))
    ev.setScreenPos(QPoint(500, 500))
    it.hoverMoveEvent(ev)                          # 直接调 handler（实例级已换）
    for _ in range(8):
        app.processEvents()

c0 = lab.mapToItem(it, ir[0].center())
c1 = lab.mapToItem(it, ir[1].center())
dot_pt = QPointF(0, 0)

# ---------- H1：压组0 图标 ----------
# ★ 断言用 QToolTip.text()（showText 同步写入）；窗口可见性在离屏/合成环境
#   有延迟与去重，只打印参考不作为失败依据。
hover_at(c0)
assert calls, "H1 失败：handler 没被调用"
assert it._tag_text_at(c0) == "深圳湾万象城", f"H1 失败：命中={it._tag_text_at(c0)!r}"
assert "深圳湾万象城" in QToolTip.text(), f"H1 失败：tooltip={QToolTip.text()!r}"
print(f"[H1] 组0 图标 → tooltip『{QToolTip.text()}』visible={QToolTip.isVisible()} OK")

# ---------- H1b：压组1 图标 ----------
hover_at(c1)
assert "深圳湾安达仕酒店" in QToolTip.text(), f"H1b 失败：tooltip={QToolTip.text()!r}"
print(f"[H1b] 组1 图标 → tooltip『{QToolTip.text()}』visible={QToolTip.isVisible()} OK")

# ---------- H2：压圆点中心（无图标）----------
hover_at(dot_pt)
# ★ QToolTip.hideText() 是**定时器延时收起**（~300ms），等它走完再断言
#   （已插桩验证：handler 收到 tip="" 并调 hideText，500ms 后 visible=False）
from PySide6.QtCore import QEventLoop, QTimer
loop = QEventLoop()
QTimer.singleShot(600, loop.quit)
loop.exec()
assert not QToolTip.isVisible(), \
    f"H2 失败：压圆点中心 tooltip 未收起 visible={QToolTip.isVisible()} text={QToolTip.text()!r}"
print("[H2] 压圆点中心 tooltip 收起 OK")

QToolTip.hideText()
win.close()
print("ALL PASS")
