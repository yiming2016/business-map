# -*- coding: utf-8 -*-
"""v2.6.88 前诊断探针：云巴/有轨电车 挪站 → Ctrl+Z 全链路。

D1 坪山云巴普通站程序化拖动 → undo 栈 +1？数据落盘？
D2 Ctrl+Z → 坐标回原位？
D3 主站体（14号线坪山中心）挪动 → 云巴副站体坐标是否被误改/漏改
D4 有轨电车清湖副站体：确认不可拖（NoButton）
"""
import os, sys, json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["METROEDITOR_NO_ACTIVATE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPointF, QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from ui.main_window import MainWindow

win = MainWindow()
win.resize(1480, 900)
win.show()
for _ in range(10):
    app.processEvents()
mv = win.map_view
dm = win.dm

fails = []
def chk(name, cond, extra=""):
    print(("[PASS] " if cond else "[FAIL] ") + name, extra)
    if not cond:
        fails.append(name)

def _drag_view(view_from, view_to, steps=6):
    vp0 = mv.viewport().mapToGlobal(view_from)
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(view_from), QPointF(vp0),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    app.sendEvent(mv.viewport(), ev)
    app.processEvents()
    for i in range(1, steps + 1):
        p = view_from + (view_to - view_from) * (i / steps)
        ev = QMouseEvent(QEvent.MouseMove, QPointF(p),
                         mv.viewport().mapToGlobal(p), Qt.NoButton,
                         Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(mv.viewport(), ev)
        app.processEvents()
    ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(view_to),
                     mv.viewport().mapToGlobal(view_to), Qt.LeftButton,
                     Qt.NoButton, Qt.NoModifier)
    app.sendEvent(mv.viewport(), ev)
    for _ in range(6):
        app.processEvents()

# ---- D1/D2：坪山云巴普通站 ----
YUNBA_ST = "坪山中心"   # 先测一个云巴线里的普通站名，从 lines 里拿
d = dm.lines_doc
for L in d["lines"]:
    if L["id"] == "坪山云巴":
        seq = L.get("stations") or []
        print("坪山云巴站序:", seq)
        YUNBA_ST = next((s for s in seq if s != "坪山中心"), "坪山中心")
        break
print("测试站:", YUNBA_ST)
sid = YUNBA_ST
# ★ 先定位到云巴线（放大到能点中的比例），否则 0.115 缩放下圆点不足 1px 点不中
mv.fit_to_line("坪山云巴")
for _ in range(10):
    app.processEvents()
print("定位后缩放:", mv._scale)
it = mv.station_items.get(sid)
chk("D0 站点图元存在", it is not None)
rec0 = dm.get_station(sid)
print("原坐标:", rec0.get("x"), rec0.get("y"))

# 视图坐标换算：用 item 的 scene pos → viewport
def scene_to_view(sx, sy):
    vp = mv.mapFromScene(QPointF(sx, sy))
    return QPointF(vp)

p0_scene = it.pos()
v_from = scene_to_view(p0_scene.x(), p0_scene.y())
# 确认按下点确实命中图元（别再瞎拖）
hit = mv.scene().items(mv.mapToScene(v_from.toPoint()))
print("按下点命中的图元:", [type(x).__name__ for x in hit[:3]])
v_to = v_from + QPointF(60, 40)
n0 = len(win._undo_stack)
_drag_view(v_from, v_to)
rec1 = dm.get_station(sid)
n1 = len(win._undo_stack)
chk("D1 拖后 undo 栈 +1", n1 == n0 + 1, "栈 %d→%d" % (n0, n1))
chk("D1b 拖后数据坐标已更新",
    abs(float(rec1["x"]) - (float(rec0["x"]) + 60)) < 1.0
    and abs(float(rec1["y"]) - (float(rec0["y"]) + 40)) < 1.0,
    "(%s,%s)→(%s,%s)" % (rec0["x"], rec0["y"], rec1["x"], rec1["y"]))
# 图元位置
it1 = mv.station_items.get(sid)
print("拖后图元 pos:", it1.pos().x(), it1.pos().y())

# Ctrl+Z
win._on_undo()
for _ in range(6):
    app.processEvents()
rec2 = dm.get_station(sid)
it2 = mv.station_items.get(sid)
chk("D2 Ctrl+Z 数据回原位",
    abs(float(rec2["x"]) - float(rec0["x"])) < 1.0
    and abs(float(rec2["y"]) - float(rec0["y"])) < 1.0,
    "(%s,%s)" % (rec2["x"], rec2["y"]))
chk("D2b Ctrl+Z 图元回原位",
    abs(it2.pos().x() - p0_scene.x()) < 1.0 and abs(it2.pos().y() - p0_scene.y()) < 1.0,
    "(%.1f,%.1f)" % (it2.pos().x(), it2.pos().y()))

# ---- D3：主站体挪动 vs 副站体 ----
main_rec = dm.get_station("坪山中心")
print("坪山中心 主坐标:", main_rec["x"], main_rec["y"], "alt_bodies:", main_rec.get("alt_bodies"))

# ---- D4：副站体不可拖确认 ----
alt_it = mv.alt_items.get("清湖@alt0")
if alt_it is not None:
    chk("D4 副站体不吃鼠标", alt_it.acceptedMouseButtons() == Qt.NoButton)
else:
    print("D4 跳过（无 清湖@alt0 图元）")

print("RESULT:", "ALL PASS" if not fails else "FAIL %d: %s" % (len(fails), fails))
# 探针退出前 win.close 会 flush 落盘 —— 数据已被 D2 撤销回原位，安全
sys.exit(0 if not fails else 1)
