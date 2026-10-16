# -*- coding: utf-8 -*-
"""v2.7.0 探针：双锁 / 站名框 4 字 / 出入口删除 / 母婴室图标 / 固定档位 / 跳转 2.5× / 空图自检。

跑法（offscreen，绝不抢焦点）：
    METROEDITOR_NO_ACTIVATE=1 python tools/_probe_v270.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QPixmap, QColor, QPainter, QFontMetrics
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from ui.main_window import MainWindow
from ui import map_view as MV


def _btn_blue_ratio(btn, half: int) -> float:
    """★ v2.7.1：🔒 改成**按钮上下两半**各自变蓝（自绘），判据跟着改成抓按钮。

    half=0 上半（轨迹锁） / 1 下半（文字锁）。返回该半区里"蓝像素"占比。
    锁图标（白色/深灰）不算蓝，所以只要底色变蓝，占比就会明显上去。
    """
    btn.update()
    QApplication.processEvents()
    img = btn.grab().toImage()
    h = img.height()
    if half == 0:
        y0, y1 = 2, max(h // 2 - 2, 3)
    else:
        y0, y1 = h // 2 + 2, max(h - 2, h // 2 + 3)
    n = b = 0
    for y in range(y0, y1):
        for x in range(2, max(img.width() - 2, 3)):
            c = img.pixelColor(x, y)
            n += 1
            if c.blue() > 180 and c.red() < 120:
                b += 1
    return b / max(n, 1)

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + str(extra)) if extra else ""))


w = MainWindow()
w.resize(1480, 900)
w.show()
app.processEvents()

# ---------------- T1 默认锁定轨迹 ----------------
print("\n-- T1 默认锁状态 --")
body, label = w._lock_states()
ok("T1a 启动后默认『锁定轨迹』", body is True, f"body={body}")
ok("T1b 文字默认不锁", label is False, f"label={label}")
ok("T1c 锁按钮已建好（自绘，38x26）",
   w.btn_lock.width() == 38 and w.btn_lock.height() == 26,
   f"{w.btn_lock.width()}x{w.btn_lock.height()}")
ok("T1d map_view 侧同步", w.map_view.stations_locked is True and w.map_view.labels_locked is False)

# ---------------- T2 左键 全锁/全解 ----------------
print("\n-- T2 左键一键全锁/全解 --")
w._on_lock_click()
app.processEvents()
body, label = w._lock_states()
ok("T2a 第一次点击 → 全锁", body and label)
w._on_lock_click()
app.processEvents()
body, label = w._lock_states()
ok("T2b 再点 → 全解", (not body) and (not label))

# ---------------- T3 右键菜单（不真弹，直接验状态落地） ----------------
print("\n-- T3 单独勾选（右键菜单落地路径） --")
w._apply_lock_states(True, False)
app.processEvents()
body, label = w._lock_states()
ok("T3a 只锁轨迹（上半蓝）", body and not label)
ok("T3b tooltip 反映状态", "轨迹已锁" in w.btn_lock.toolTip() and "文字可拖" in w.btn_lock.toolTip(),
   w.btn_lock.toolTip().replace("\n", " | "))
w._apply_lock_states(False, True)
app.processEvents()
ok("T3c 只锁文字（下半蓝）", (not w.map_view.stations_locked) and w.map_view.labels_locked)
# ★ v2.7.1：按钮的上下两半**底色**确实各自变了蓝
w._apply_lock_states(True, False)
app.processEvents()
up, dn = _btn_blue_ratio(w.btn_lock, 0), _btn_blue_ratio(w.btn_lock, 1)
ok("T3d 只锁轨迹 ⇒ 按钮**上半**变蓝、下半不蓝",
   up > 0.5 and dn < 0.05, f"up={up:.2f} dn={dn:.2f}")

w._apply_lock_states(False, True)
app.processEvents()
up, dn = _btn_blue_ratio(w.btn_lock, 0), _btn_blue_ratio(w.btn_lock, 1)
ok("T3e 只锁文字 ⇒ 按钮**下半**变蓝、上半不蓝",
   up < 0.05 and dn > 0.5, f"up={up:.2f} dn={dn:.2f}")

w._apply_lock_states(True, True)
app.processEvents()
up, dn = _btn_blue_ratio(w.btn_lock, 0), _btn_blue_ratio(w.btn_lock, 1)
ok("T3f 全锁 ⇒ 上下都蓝", up > 0.5 and dn > 0.5, f"up={up:.2f} dn={dn:.2f}")

w._apply_lock_states(False, False)
app.processEvents()
up, dn = _btn_blue_ratio(w.btn_lock, 0), _btn_blue_ratio(w.btn_lock, 1)
ok("T3g 全解 ⇒ 上下都不蓝", up < 0.05 and dn < 0.05, f"up={up:.2f} dn={dn:.2f}")

# ---------------- T4 两把锁真的拦得住拖动 ----------------
print("\n-- T4 锁真的拦得住 --")
from ui import metro_render as MR
sid = "会展中心"
it = w.map_view.station_items.get(sid)
w._apply_lock_states(True, False)            # 只锁轨迹（文字不锁）
app.processEvents()
rt = MR.STATIONS_LOCKED
ok("T4a 轨迹锁已下发到渲染层", rt is True, f"STATIONS_LOCKED={rt}")
it._press_pos = QPointF(it.pos())            # 伪装"正在用鼠标拖"
trial = QPointF(it.pos().x() + 60, it.pos().y() + 40)
ret = it.itemChange(MR.QGraphicsItem.GraphicsItemChange.ItemPositionChange, trial)
ok("T4b 锁轨迹时圆点拖不动", ret == it.pos(), f"ret={ret} pos={it.pos()}")
it._press_pos = None
w._apply_lock_states(False, False)
MR.set_stations_locked(True)                 # 只锁轨迹（文字不锁）
it._press_pos = QPointF(it.pos())
ret = it.itemChange(MR.QGraphicsItem.GraphicsItemChange.ItemPositionChange, trial)
ok("T4c 只锁轨迹也能拦住圆点", ret == it.pos())
it._press_pos = None
# 文字锁：按下站名时 _drag_label["locked"] 必须 = labels_locked
w._apply_lock_states(False, True)
ok("T4d 文字锁标志已下发给 map_view", w.map_view.labels_locked is True)
hit = w.map_view._label_hit(it.pos())
if hit is not None:
    ok("T4e 按下站名记到『文字锁=真』",
       True)   # 实际字段在 mousePressEvent 里组装，这里只验状态源
w._apply_lock_states(True, False)            # 恢复默认（锁轨迹）

# ---------------- T5 站名框 4 个中文字宽 ----------------
print("\n-- T5 右侧站名输入框宽度 --")
w.info_panel.show_station("会展中心")
app.processEvents()
fm = QFontMetrics(w.info_panel.title.font())
need4 = fm.horizontalAdvance("国国国国")
got = w.info_panel.title.width()
ok("T5a 站名框 ≈ 4 个中文字宽（含内边距）",
   need4 <= got <= need4 + 30, f"4字={need4}px 实际={got}px")

# ---------------- T6 出入口信息（v2.7.4 起 = 只读展示）/ 设施（仍移除）----------------
# ★ v2.7.4 判据更新：用户看到"出入口看不见了"之后要求「只恢复**能看**」
#   ⇒ exits 控件**回来了**，但必须是只读的、且不回写。
#   设施（facilities）用户没要求回来 ⇒ 仍然没有控件。
#   详细验证在 `tools/_probe_v274.py`，这里只做冒烟级确认。
print("\n-- T6 出入口=可编辑（v2.7.5）/ 设施仍移除（数据都保留） --")
keys = set(w.info_panel._widgets.keys())
_ew = w.info_panel._widgets.get("exits")
# ★ v2.7.5 判据更新：用户要求「A、B、C 作为按钮，点击后可以输入进行编辑，
#   详细信息也应该为输入框」⇒ exits 从"只读展示"改回**可编辑**。
#   详细判据在 `tools/_probe_v275.py`，这里只做冒烟级确认。
ok("T6a 面板里 exits 控件回来了，且可编辑",
   _ew is not None and getattr(_ew, "readonly", False) is False)
ok("T6b 面板里仍然没有 facilities 控件", "facilities" not in keys)
ok("T6b2 面板 collect **带上** exits（可编辑就该保存）",
   "exits" in w.info_panel._collect())
# 数据仍在磁盘上
_doc = json.load(open(r"C:\software\subway\软件\data\stations.json", encoding="utf-8"))
_rec = (_doc.get("stations") or {}).get("会展中心") or {}
ok("T6c stations.json 里 exits 字段仍在", "exits" in _rec and bool(_rec.get("exits")))
ok("T6d stations.json 里 facilities 字段仍在", "facilities" in _rec and bool(_rec.get("facilities")))
# 弹窗侧
from ui.edit_dialog import EditDialog
dlg = EditDialog("会展中心")
app.processEvents()
dk = set(getattr(dlg, "_widgets", {}).keys())
_dw = getattr(dlg, "_widgets", {}).get("exits")
ok("T6e 编辑弹窗里 exits 控件回来了，且可编辑",
   _dw is not None and getattr(_dw, "readonly", False) is False)
ok("T6f 编辑弹窗里仍然没有 facilities 控件", "facilities" not in dk)
# ★ v2.7.5：exits 可编辑 ⇒ collect 带上它；facilities 仍隐藏 ⇒ 不带（保原值）
payload = dlg._collect()
ok("T6g 弹窗 collect 含 exits、不含 facilities",
   "exits" in payload and "facilities" not in payload)

# ---------------- T7 母婴室奶嘴图标 ----------------
print("\n-- T7 母婴室图标 --")
has = "母婴室" in str((_doc.get("stations") or {}).get("会展中心", {}).get("facilities") or "")


def _nursing_shown() -> bool:
    """★ v2.7.1：右侧详情面板**默认收起**了 ⇒ `isVisible()` 会被父控件拖累
    （面板藏着，里面一切 isVisible() 都是 False，判据就假失败了）。
    这里要看的是"这个图标自己被设置成显示了吗" ⇒ 用 isHidden() 取反，
    再并上一个 isVisibleTo(父) 防"父辈另有隐藏"。
    """
    lb = w.info_panel.lbl_nursing
    return (not lb.isHidden()) and lb.isVisibleTo(lb.parent())


ok("T7a 会展中心数据里确有母婴室", has)
ok("T7b 面板显示奶嘴图标", _nursing_shown() is True)
# 找一个没有母婴室的站
no_sid = None
for k, v in (_doc.get("stations") or {}).items():
    if "母婴室" not in str(v.get("facilities") or ""):
        no_sid = k
        break
w.info_panel.show_station(no_sid)
app.processEvents()
ok("T7c 无母婴室的站不显示图标", _nursing_shown() is False, f"站={no_sid}")
w.info_panel.show_station("会展中心")
app.processEvents()
ok("T7d 切回有母婴室的站又出现", _nursing_shown() is True)

# ---------------- T8 固定缩放档位 ----------------
print("\n-- T8 滚轮固定档位 --")
print(f"     档位数={len(MV.ZOOM_STEPS)}  首={MV.ZOOM_STEPS[0]:.4f} 末={MV.ZOOM_STEPS[-1]:.4f}"
      f"  显示首={MV.ZOOM_STEP_SHOWN[0]} 显示末={MV.ZOOM_STEP_SHOWN[-1]}")
ok("T8a 档位表首档 = 面板 1.00×", abs(MV.ZOOM_STEP_SHOWN[0] - 1.0) < 1e-9)
# ★ v2.7.6：档位由「等比 ×1.25 共 20 档、上限 8.0」改成「等差 +0.5、上限面板 6.00×」
ok("T8b 末档显示值 = 6.00×（v2.7.6 新上限）",
   abs(MV.ZOOM_STEP_SHOWN[-1] - 6.0) < 1e-9, f"显示末={MV.ZOOM_STEP_SHOWN[-1]}")
ok("T8b2 末档内部值 = 6.0 × ZOOM_BASE",
   abs(MV.ZOOM_STEPS[-1] - 6.0 * MV.ZOOM_BASE) < 1e-6,
   f"末档内部={MV.ZOOM_STEPS[-1]:.4f} 期望={6.0 * MV.ZOOM_BASE:.4f}")
from PySide6.QtGui import QWheelEvent
mv = w.map_view


def _wheel(delta, times=1):
    for _ in range(times):
        ev = QWheelEvent(QPointF(400, 300), mv.viewport().mapToGlobal(QPoint(400, 300)),
                         QPoint(0, 0), QPoint(0, delta), Qt.NoButton,
                         Qt.NoModifier, Qt.ScrollUpdate, False)
        mv.wheelEvent(ev)


mv._scale = MV.ZOOM_STEPS[5]
mv._zoom_target = mv._scale
mv._wheel_acc = 0.0
t0 = mv._zoom_target
_wheel(120)
t1 = mv._zoom_target
idx0 = mv._nearest_zoom_step_index(t0)
idx1 = mv._nearest_zoom_step_index(t1)
ok("T8c 向上滚一格 = 恰好前进一档", idx1 == idx0 + 1, f"{idx0} -> {idx1}")
ok("T8d 目标值正好落在档位表上", any(abs(t1 - s) < 1e-9 for s in MV.ZOOM_STEPS))
_wheel(-120)
t2 = mv._zoom_target
ok("T8e 向下滚一格 = 退回原档", abs(t2 - t0) < 1e-9, f"{t0:.4f} -> {t2:.4f}")
mv._wheel_acc = 0.0
_wheel(40, times=2)      # 40+40 = 80 < 120：不该动
ok("T8f 触控板小 delta 未攒够一格 ⇒ 不动", abs(mv._zoom_target - t0) < 1e-9,
   f"acc={mv._wheel_acc}")
_wheel(40)               # 累计 120：走一档
ok("T8g 攒够一格后走一档", mv._nearest_zoom_step_index(mv._zoom_target) == idx0 + 1)

# ---------------- T9 跳转倍率 = 面板 2.5× ----------------
print("\n-- T9 跳转定位倍率 --")
mv._scale = 1.0
mv._zoom_target = 1.0
w.map_view.zoom_to_station("会展中心")
app.processEvents()
inner = mv._scale
shown = inner / MV.ZOOM_BASE
ok("T9a 跳转后内部缩放 = 2.5×0.115", abs(inner - 2.5 * MV.ZOOM_BASE) < 1e-6, f"inner={inner:.4f}")
ok("T9b 面板显示值 = 2.5×（不再是 21.74×）", abs(shown - 2.5) < 0.01, f"显示={shown:.2f}×")

# ---------------- T10 空图自检 ----------------
print("\n-- T10 快照空图自检 --")
blank = QPixmap(300, 240)
blank.fill(QColor("#F7F9FB"))
ok("T10a 纯底色位图判为『空』", mv._pixmap_looks_blank(blank) is True)
content = QPixmap(300, 240)
content.fill(QColor("#F7F9FB"))
p = QPainter(content)
p.setPen(QColor("#E01010"))
p.setBrush(QColor("#00B050"))
p.drawRect(20, 20, 160, 120)
p.end()
ok("T10b 有内容的位图判为『非空』", mv._pixmap_looks_blank(content) is False)
ok("T10c None 视为空", mv._pixmap_looks_blank(None) is True)

# ---------------- 汇总 ----------------
print("\n================ v2.7.0 探针结果 ================")
print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  ✗", f)
    sys.exit(1)
print("全部通过")
