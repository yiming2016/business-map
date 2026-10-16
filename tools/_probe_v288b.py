# -*- coding: utf-8 -*-
"""v2.6.88 探针②：直接驱动 view 层「挪站确定性收尾」分支。

（合成鼠标的 scenePos 映射在 offscreen 下不可靠 —— 内建拖拽按 event.scenePos
  搬图元会瞬移到 (0,0)，故不再用鼠标事件模拟拖动，改为设置 _press_dot 后
  发真实的 release 事件给 viewport，验证 view 层收尾：数据同步+上报+撤销。）

T1 主站拖动收尾 → 数据更新 + undo +1 + Ctrl+Z 回位（含图元）
T2 副站体拖动收尾 → alt_bodies[i] 更新 + 主坐标不动 + Ctrl+Z 回位
T3 单击（未拖动）→ 选中主站、不落盘
T4 grabber 不卡
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

BAK = "data/stations.json.bak_probe288b_%s" % time.strftime("%H%M%S")
shutil.copy("data/stations.json", BAK)

fails = []
def chk(name, cond, extra=""):
    print(("[PASS] " if cond else "[FAIL] ") + name, extra)
    if not cond:
        fails.append(name)

def qwait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

def release_at(item, press_scene_pos, moved_to=None):
    """把 _press_dot 设好 + item 摆到位 + 向 viewport 发 release。"""
    mv._press_dot = item
    mv._press_dot_pos = QPointF(press_scene_pos)
    if moved_to is not None:
        item.setPos(QPointF(moved_to[0], moved_to[1]))
    v = QPointF(mv.mapFromScene(item.pos()))
    vp0 = mv.viewport().mapToGlobal(v)
    ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(v), QPointF(vp0),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    app.sendEvent(mv.viewport(), ev)
    for _ in range(8):
        app.processEvents()

# ---------- T1 主站确定性收尾 ----------
mv.fit_to_line("坪山云巴"); qwait(800)
for _ in range(10): app.processEvents()
it = mv.station_items["坪山高铁站"]
rec0 = dm.get_station("坪山高铁站")
p0 = QPointF(float(rec0["x"]), float(rec0["y"]))   # ★ 立刻抄值（get_station 是活引用）
n0 = len(win._undo_stack)
release_at(it, p0, (p0.x() + 40, p0.y() + 30))
rec1 = dm.get_station("坪山高铁站")
chk("T1 拖动落盘", abs(float(rec1["x"]) - (p0.x() + 40)) < 1 and abs(float(rec1["y"]) - (p0.y() + 30)) < 1,
    "(%s,%s)" % (rec1["x"], rec1["y"]))
chk("T1b undo 栈 +1", len(win._undo_stack) == n0 + 1)
win._on_undo(); qwait(400)
for _ in range(8): app.processEvents()
rec2 = dm.get_station("坪山高铁站")
it2 = mv.station_items["坪山高铁站"]
chk("T1c Ctrl+Z 数据回位", abs(float(rec2["x"]) - p0.x()) < 1 and abs(float(rec2["y"]) - p0.y()) < 1)
chk("T1d Ctrl+Z 图元回位",
    abs(it2.pos().x() - p0.x()) < 1 and abs(it2.pos().y() - p0.y()) < 1)

# ---------- T2 副站体确定性收尾 ----------
rec0 = dm.get_station("坪山中心")
b0 = dict(rec0["alt_bodies"][0])
ait = mv.alt_items.get("坪山中心@alt0")
chk("T2 副站体图元存在", ait is not None)
if ait is not None:
    n0 = len(win._undo_stack)
    release_at(ait, QPointF(b0["x"], b0["y"]), (b0["x"] + 30, b0["y"] + 20))
    rec1 = dm.get_station("坪山中心")
    b1 = rec1["alt_bodies"][0]
    chk("T2b alt_bodies 落盘", abs(b1["x"] - (b0["x"] + 30)) < 1 and abs(b1["y"] - (b0["y"] + 20)) < 1,
        "(%s,%s)" % (b1["x"], b1["y"]))
    chk("T2c 主坐标不动", rec1["x"] == rec0["x"] and rec1["y"] == rec0["y"])
    chk("T2d undo 栈 +1", len(win._undo_stack) == n0 + 1)
    win._on_undo(); qwait(400)
    for _ in range(8): app.processEvents()
    rec2 = dm.get_station("坪山中心")
    b2 = rec2["alt_bodies"][0]
    chk("T2e Ctrl+Z 副站体回位", abs(b2["x"] - b0["x"]) < 1 and abs(b2["y"] - b0["y"]) < 1)

# ---------- T3 单击不落盘、选中主站 ----------
it = mv.station_items["清龙"]
rec0 = dm.get_station("清龙")
q0 = (float(rec0["x"]), float(rec0["y"]))
n0 = len(win._undo_stack)
release_at(it, QPointF(*q0))   # 原地 release = 单击
rec1 = dm.get_station("清龙")
chk("T3 单击不落盘", float(rec1["x"]) == q0[0] and float(rec1["y"]) == q0[1])
chk("T3b undo 栈不变", len(win._undo_stack) == n0)

# ---------- T4 grabber 不卡 ----------
chk("T4 grabber 已释放", mv.scene().mouseGrabberItem() is None)

# ---------- 还原数据 ----------
shutil.copy(BAK, "data/stations.json")
os.remove(BAK)
print("RESULT:", "ALL PASS" if not fails else "FAIL %d: %s" % (len(fails), fails))
sys.exit(0 if not fails else 1)
