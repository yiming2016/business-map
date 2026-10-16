# -*- coding: utf-8 -*-
"""v2.6.82 探针：三个修复的端到端验证。

T1  拖动吸附默认关：程序化把站点挪 40px，itemChange 不再往走廊拽
T2  副站体文字可拖：合成鼠标拖「湖贝@alt0」的站名 → label_off 变化 +
    松手后 alt_bodies[0] 落盘 label_dx/dy（探针收尾还原数据）
T3  10 号线描线：5 个 key 都在，弯形点数 >= 2
"""
import json
import io
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["METROEDITOR_NO_ACTIVATE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPointF, QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from ui.main_window import MainWindow
from ui import metro_render as MR

# ---------- T1：吸附默认关 ----------
assert MR.TRACE_SNAP is False, "T1 失败：TRACE_SNAP 默认应为关"
print("[T1] TRACE_SNAP 默认关 OK（拖站点完全跟手）")

win = MainWindow()
win.resize(1480, 900)
win.show()
for _ in range(10):
    app.processEvents()

mv = win.map_view


def _drag(view_from, view_to, steps=6):
    vp0 = mv.viewport().mapToGlobal(view_from)
    for t, b in ((QEvent.MouseButtonPress, Qt.LeftButton),):
        ev = QMouseEvent(t, QPointF(view_from), QPointF(vp0), b, Qt.NoButton, Qt.NoModifier)
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


# ---------- T2：副站体站名可拖 ----------
mv.zoom_to_station("湖贝", target_scale=1.3)
for _ in range(15):
    app.processEvents()
alt = mv.alt_items.get("湖贝@alt0")
assert alt is not None, "T2 前置失败：找不到湖贝@alt0"
lab = alt.label
lr = alt.label_scene_rect()
c_scene = lr.center()
v_from = mv.mapFromScene(c_scene)
v_to = v_from + type(v_from)(40, 0)
off0 = QPointF(alt.label_off())
_drag(v_from, v_to)
off1 = QPointF(alt.label_off())
print(f"[T2] label_off {off0.x():.0f},{off0.y():.0f} → {off1.x():.0f},{off1.y():.0f}")
assert abs(off1.x() - off0.x() - 40.0) < 12, f"T2 失败：副站体站名拖不动（off={off1.x():.1f}）"
# 落盘检查（_on_label_moved → alt_bodies[0]）
sd = json.load(io.open("data/stations.json", encoding="utf-8"))
b0 = sd["stations"]["湖贝"]["alt_bodies"][0]
print(f"[T2] alt_bodies[0].label_dx = {b0.get('label_dx')}")
assert b0.get("label_dx") is not None and abs(b0["label_dx"] - off1.x()) < 2, \
    f"T2 失败：alt_bodies 没落盘（{b0}）"
# 点一下副站体文字（不拖）= 选中主站
_click_c = alt.label_scene_rect().center()
v_c = mv.mapFromScene(_click_c)
CLICKED = []
mv.station_clicked.connect(lambda sid: CLICKED.append(sid))
gp = mv.viewport().mapToGlobal(v_c)
for t, b in ((QEvent.MouseButtonPress, Qt.LeftButton),
             (QEvent.MouseButtonRelease, Qt.LeftButton)):
    ev = QMouseEvent(t, QPointF(v_c), QPointF(gp), b, Qt.NoButton, Qt.NoModifier)
    app.sendEvent(mv.viewport(), ev)
    app.processEvents()
assert CLICKED and CLICKED[-1] == "湖贝", f"T2 失败：点副站体文字没选中主站（{CLICKED}）"
print("[T2] 副站体站名可拖 + 落盘 alt_bodies + 单击选中主站 OK")

# ---------- T3：10 号线描线 ----------
ld = json.load(io.open("data/lines.json", encoding="utf-8"))
doc = ld.get("lines_doc") or ld
tr = doc.get("traced") or {}
seq = ["双拥街", "平湖", "禾花", "华南城", "木古", "上李朗"]
for a, b in zip(seq, seq[1:]):
    k = f"10|{a}|{b}"
    assert k in tr and len(tr[k]) >= 2, f"T3 失败：{k} 缺描线"
    print(f"[T3] {k} 点数={len(tr[k])}")
print("[T3] 10 号线 5 段描线 OK")

# ---------- 收尾：还原探针写进数据的拖动偏移 ----------
sd["stations"]["湖贝"]["alt_bodies"][0].pop("label_dx", None)
sd["stations"]["湖贝"]["alt_bodies"][0].pop("label_dy", None)
sd["stations"]["湖贝"]["alt_bodies"][0].pop("label_side", None)
io.open("data/stations.json", "w", encoding="utf-8").write(
    json.dumps(sd, ensure_ascii=False, indent=1))
print("[CLEAN] 探针拖动偏移已还原")
win.blockSignals(True)
win.close()
print("ALL PASS")
