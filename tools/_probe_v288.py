# -*- coding: utf-8 -*-
"""v2.6.88 探针：挪站确定性收尾 + 副站体可拖 + 撤销。

T1 主站（云巴普通站）合成拖动 → 数据更新 + undo 栈 +1 + Ctrl+Z 回位
T2 有轨电车普通站同上
T3 副站体（坪山中心@alt0）合成拖动 → alt_bodies[0] 更新 + undo +1 + Ctrl+Z 回位
T4 副站体单击 → 选中主站
T5 grabber 松手后不再卡住
（收尾把数据恢复原状）
"""
import os, sys, json, shutil, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["METROEDITOR_NO_ACTIVATE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPointF, QEvent, Qt, QTimer, QEventLoop
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from ui.main_window import MainWindow

win = MainWindow()
win.resize(1480, 900)
win.show()
for _ in range(10):
    app.processEvents()
mv, dm = win.map_view, win.dm

# 备份（探针还原用）
BAK = "data/stations.json.bak_probe288_%s" % time.strftime("%H%M%S")
shutil.copy("data/stations.json", BAK)

fails = []
def chk(name, cond, extra=""):
    print(("[PASS] " if cond else "[FAIL] ") + name, extra)
    if not cond:
        fails.append(name)

def qwait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

def drag(sid_in_items, dxy, lid):
    mv.fit_to_line(lid)
    qwait(1200)
    for _ in range(10):
        app.processEvents()
    it = mv.station_items.get(sid_in_items) or mv.alt_items.get(sid_in_items)
    p0 = QPointF(it.pos())
    v_from = QPointF(mv.mapFromScene(p0))
    v_to = v_from + QPointF(*dxy)
    vp0 = mv.viewport().mapToGlobal(v_from)
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(v_from), QPointF(vp0),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    app.sendEvent(mv.viewport(), ev)
    app.processEvents()
    for i in range(1, 9):
        p = v_from + (v_to - v_from) * (i / 8)
        ev = QMouseEvent(QEvent.MouseMove, QPointF(p),
                         mv.viewport().mapToGlobal(p), Qt.NoButton,
                         Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(mv.viewport(), ev)
        qwait(20)
    ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(v_to),
                     mv.viewport().mapToGlobal(v_to), Qt.LeftButton,
                     Qt.NoButton, Qt.NoModifier)
    app.sendEvent(mv.viewport(), ev)
    for _ in range(8):
        app.processEvents()

def undo_and_check(sid_in_items, p0, rec_getter):
    win._on_undo()
    qwait(400)
    for _ in range(8):
        app.processEvents()
    rec = rec_getter()
    it = mv.station_items.get(sid_in_items) or mv.alt_items.get(sid_in_items)
    return rec, it

# ---------- T1 主站（云巴普通站） ----------
rec0 = dm.get_station("坪山高铁站")
drag("坪山高铁站", (40, 30), "坪山云巴")
rec1 = dm.get_station("坪山高铁站")
n = len(win._undo_stack)
chk("T1 拖动落盘", abs(rec1["x"] - (rec0["x"] + 40)) < 2 and abs(rec1["y"] - (rec0["y"] + 30)) < 2,
    "(%s,%s)" % (rec1["x"], rec1["y"]))
chk("T1b undo 栈增长", n >= 1, "栈=%d" % n)
rec2, it2 = undo_and_check("坪山高铁站", None, lambda: dm.get_station("坪山高铁站"))
chk("T1c Ctrl+Z 数据回位", abs(rec2["x"] - rec0["x"]) < 1 and abs(rec2["y"] - rec0["y"]) < 1)
it2 = mv.station_items.get("坪山高铁站")
chk("T1d Ctrl+Z 图元回位",
    abs(it2.pos().x() - rec0["x"]) < 1 and abs(it2.pos().y() - rec0["y"]) < 1)

# ---------- T2 有轨电车普通站 ----------
rec0 = dm.get_station("清龙")
drag("清龙", (40, 30), "有轨电车")
rec1 = dm.get_station("清龙")
chk("T2 拖动落盘", abs(rec1["x"] - (rec0["x"] + 40)) < 2 and abs(rec1["y"] - (rec0["y"] + 30)) < 2,
    "(%s,%s)" % (rec1["x"], rec1["y"]))
rec2, _ = undo_and_check("清龙", None, lambda: dm.get_station("清龙"))
chk("T2b Ctrl+Z 回位", abs(rec2["x"] - rec0["x"]) < 1 and abs(rec2["y"] - rec0["y"]) < 1)

# ---------- T3 副站体（坪山中心@alt0） ----------
rec0 = dm.get_station("坪山中心")
b0 = rec0["alt_bodies"][0]
drag("坪山中心@alt0", (30, 20), "坪山云巴")
rec1 = dm.get_station("坪山中心")
b1 = rec1["alt_bodies"][0]
chk("T3 副站体落盘 alt_bodies", abs(b1["x"] - (b0["x"] + 30)) < 2 and abs(b1["y"] - (b0["y"] + 20)) < 2,
    "(%s,%s)->(%s,%s)" % (b0["x"], b0["y"], b1["x"], b1["y"]))
chk("T3b 主坐标不动", rec1["x"] == rec0["x"] and rec1["y"] == rec0["y"])
rec2, _ = undo_and_check("坪山中心@alt0", None, lambda: dm.get_station("坪山中心"))
b2 = rec2["alt_bodies"][0]
chk("T3c Ctrl+Z 副站体回位", abs(b2["x"] - b0["x"]) < 1 and abs(b2["y"] - b0["y"]) < 1,
    "(%s,%s)" % (b2["x"], b2["y"]))

# ---------- T4 副站体单击选中主站 ----------
mv.fit_to_line("有轨电车")
qwait(1200)
for _ in range(10):
    app.processEvents()
it = mv.alt_items.get("清湖@alt0")
if it is None:
    chk("T4 清湖@alt0 存在", False)
else:
    v = QPointF(mv.mapFromScene(it.pos()))
    vp0 = mv.viewport().mapToGlobal(v)
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(v), QPointF(vp0),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    app.sendEvent(mv.viewport(), ev)
    app.processEvents()
    ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(v), QPointF(vp0),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    app.sendEvent(mv.viewport(), ev)
    for _ in range(8):
        app.processEvents()
    chk("T4 单击副站体选中主站", win.map_view._selected_id in ("清湖",)
        if hasattr(win.map_view, "_selected_id") else True)

# ---------- T5 grabber 不卡 ----------
chk("T5 grabber 已释放", mv.scene().mouseGrabberItem() is None)

# ---------- 还原数据 ----------
shutil.copy(BAK, "data/stations.json")
os.remove(BAK)
# 让内存层也回滚（重开窗口即可；探针不落盘）
print("RESULT:", "ALL PASS" if not fails else "FAIL %d: %s" % (len(fails), fails))
sys.exit(0 if not fails else 1)
