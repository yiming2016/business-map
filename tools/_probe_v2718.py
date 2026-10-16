# -*- coding: utf-8 -*-
"""v2.7.18 探针：① ⚙️ 里可设右侧面板宽度（并记住拖出来的宽度）
                ② 看图模式悬浮：气泡 + 圆点放大。

用户原话：「在⚙️里面变成可以设置的项目」「看图模式在鼠标悬浮在站点文字上时
没有悬浮显示、站点圆圈没有放大，是否可以修复？」

病根：看图模式把 842 个矢量图元全 `setVisible(False)`（`_hide_vector_items`），
隐藏图元不收 hover 事件 ⇒ 光晕/气泡/手型光标全部消失。修法 = 进看图模式时
按**烘图基准**（PX_PER_UNIT）建一张命中表，鼠标移动时反查。
"""
import os
import sys

os.environ["METROEDITOR_NO_VIEW_START"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

import json                                                 # noqa: E402
from pathlib import Path                                    # noqa: E402

from PySide6.QtCore import QPointF, QRectF, Qt              # noqa: E402
from PySide6.QtGui import QImage                            # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402
from PySide6.QtTest import QTest                            # noqa: E402

app = QApplication(sys.argv)

from ui.main_window import MainWindow                       # noqa: E402
from ui import image_mode as IM                             # noqa: E402

FAILS = []
N_OK = 0


def ok(name, cond, info=""):
    global N_OK
    if cond:
        N_OK += 1
        print(f"  [OK] {name}" + (f"  —— {info}" if info else ""))
    else:
        FAILS.append(name)
        print(f"  [FAIL] {name}" + (f"  —— {info}" if info else ""))


def pump(n=12):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


win = MainWindow()
win.resize(1400, 860)
win.show()
pump(25)
mv = win.map_view
d = win._data_dir()

# ======================================================================
# A. ⚙️ 里的「右侧面板宽度」
# ======================================================================
print("\n[A] 右侧面板宽度设置")

# A1 默认值 520（且落在 360~780 内）
w0 = win._saved_info_w()
ok("A1 设置里的默认面板宽 = 520", w0 == 520, f"读到 {w0}")

# A2 弹窗能把数字带出来（不 exec：离屏下模态对话框会挂死）
from ui.image_settings_dialog import ImageSettingsDialog     # noqa: E402
sec = IM.load_settings(d)
sec["info_panel_w"] = 610
dlg = ImageSettingsDialog(win, sec, d)
ok("A2 弹窗读进设置值 610", int(dlg.sp_info_w.value()) == 610,
   f"spin={dlg.sp_info_w.value()}")
dlg.sp_info_w.setValue(455)
res = dlg.result_settings()
ok("A3 弹窗回写 info_panel_w", res.get("info_panel_w") == 455,
   f"result={res.get('info_panel_w')}")

# A4 落盘 + 读回
sec2 = dict(IM.load_settings(d))
old_w = sec2.get("info_panel_w", 520)
sec2["info_panel_w"] = 600
IM.save_settings(d, sec2)
ok("A4 写盘后能读回 600", int(IM.load_settings(d).get("info_panel_w")) == 600)
ok("A5 _saved_info_w() 跟到 600", win._saved_info_w() == 600,
   f"={win._saved_info_w()}")

# A6 限幅：塞个离谱值进来也得夹回 360~780
sec3 = dict(IM.load_settings(d))
sec3["info_panel_w"] = 9999
IM.save_settings(d, sec3)
ok("A6 超限值被夹到 780", win._saved_info_w() == 780, f"={win._saved_info_w()}")

# A7 拖面板边缘 ⇒ 防抖写盘（拖动走到 _set_info_w）
sec4 = dict(IM.load_settings(d))
sec4["info_panel_w"] = 520
IM.save_settings(d, sec4)
win._set_info_w(660)
ok("A7a 拖动后内存宽度 = 660", win._info_w == 660, f"={win._info_w}")
QTest.qWait(900)
pump(4)
ok("A7b 拖动 600ms 后写进设置", int(IM.load_settings(d).get("info_panel_w")) == 660,
   f"={IM.load_settings(d).get('info_panel_w')}")

# A8 ⚙️ 里改数字 ⇒ 立刻生效（_apply_info_w_from_settings）
sec5 = dict(IM.load_settings(d))
sec5["info_panel_w"] = 480
IM.save_settings(d, sec5)
win._apply_info_w_from_settings()
ok("A8 应用设置后宽度 = 480", win._info_w == 480, f"={win._info_w}")

# 复原用户原本的设置值
sec6 = dict(IM.load_settings(d))
sec6["info_panel_w"] = old_w
IM.save_settings(d, sec6)
win._apply_info_w_from_settings()

# ======================================================================
# B. 看图模式悬浮命中
# ======================================================================
print("\n[B] 看图模式悬浮命中")
n_st = len(mv.station_items) + len(getattr(mv, "alt_items", {}) or {})
# 手工进看图模式（不烘图：hover 跟位图内容无关，只要命中表建起来）
img = QImage(64, 64, QImage.Format_RGB32)
img.fill(Qt.white)
rect = mv._elements_rect() or QRectF(0, 0, 8000, 6000)
mv.enter_view_mode(img, rect)
pump(6)
ok("B1 命中表建起来了", len(getattr(mv, "_view_hit", []) or []) == n_st,
   f"{len(mv._view_hit)}/{n_st}")
ok("B2 确实在看图模式", bool(mv._view_mode))

# B3 圆点中心 ⇒ 命中自己
its = list(mv.station_items.values())
hit_ok, hit_bad = 0, []
for it in its[:60]:
    got = mv.view_hit_station(QPointF(it.pos()))
    if got is it:
        hit_ok += 1
    elif got is not None:
        hit_bad.append((it.station_id, getattr(got, "station_id", "?")))
ok("B3 站点圆心命中自己（抽 60 个）", hit_ok == min(60, len(its)),
   f"{hit_ok}/{min(60, len(its))} 错判样例={hit_bad[:3]}")

# B4 站名框中心 ⇒ 命中自己（挑一个字框中心不在任何圆点内的站，走字框分支）
lab_ok, lab_pick = 0, 0
for it in its:
    try:
        lr = it.label_scene_rect()
    except Exception:
        continue
    c = QPointF(lr.center())
    inside = False
    for _i2, cx, cy, r, _lr in mv._view_hit:
        dx, dy = c.x() - cx, c.y() - cy
        if dx * dx + dy * dy <= r * r:
            inside = True
            break
    if inside:
        continue                      # 会被圆点分支抢走，不算字框判据
    lab_pick += 1
    if mv.view_hit_station(c) is it:
        lab_ok += 1
    if lab_pick >= 30:
        break
ok("B4 站名框中心命中自己（字框分支）", lab_pick >= 5 and lab_ok >= lab_pick * 0.8,
   f"{lab_ok}/{lab_pick}")

# B5 空白 ⇒ None
far = QPointF(rect.left() - 500.0, rect.top() - 500.0)
ok("B5 空白处不命中", mv.view_hit_station(far) is None)

# B6 悬浮光晕状态（set_view_hover）
it0 = its[0] if its else None
if it0 is not None:
    mv.set_view_hover(it0)
    ok("B6a 记住了悬浮站", mv._view_hover_sid == it0.station_id,
       f"={mv._view_hover_sid}")
    mv.set_view_hover(None)
    ok("B6b 移开后清空", mv._view_hover_sid == "" and mv._view_hover_item is None)

# B7 ★ 端到端：走 MainWindow._handle_hover（看图模式分支）⇒ 气泡真的弹出来
calls = []


def _spy_show_for(gpos, data, images=None):
    calls.append((data.get("station_id") or data.get("station_name"), images))


win.tip.show_for = _spy_show_for
it1 = its[3] if len(its) > 3 else it0
vp = QPointF(50.0, 50.0)          # 视口坐标（只用于算气泡的屏幕位置）
win._handle_hover_view_mode(QPointF(it1.pos()), vp)
ok("B7a 悬浮站点 ⇒ 弹气泡", len(calls) == 1 and calls[0][0] == it1.station_id,
   f"calls={[c[0] for c in calls]}")
calls.clear()
win._handle_hover_view_mode(far, vp)
ok("B7b 悬浮空白 ⇒ 收气泡（不弹）", len(calls) == 0, f"calls={len(calls)}")

# B8 站名位置也能触发气泡（用户原话：「悬浮在站点文字上时没有悬浮显示」）
if lab_pick:
    got_lab = None
    for it in its:
        try:
            lr = it.label_scene_rect()
        except Exception:
            continue
        c = QPointF(lr.center())
        inside = False
        for _i2, cx, cy, r, _lr in mv._view_hit:
            dx, dy = c.x() - cx, c.y() - cy
            if dx * dx + dy * dy <= r * r:
                inside = True
                break
        if inside:
            continue
        got_lab = (it, c)
        break
    if got_lab is not None:
        itl, cl = got_lab
        calls.clear()
        win._handle_hover_view_mode(cl, vp)
        ok("B8 悬浮站名文字 ⇒ 也弹气泡",
           len(calls) == 1 and calls[0][0] == itl.station_id,
           f"站={itl.station_id} calls={[c[0] for c in calls]}")

# B9 光标：看图模式下压到站点 ⇒ 手型（_sync_cursor 走同一套命中）
if it0 is not None:
    kind_before = mv._cursor_kind
    mv._cursor_probe = QPointF(-99, -99)
    mv._sync_cursor(mv.mapFromScene(QPointF(it0.pos())), force=True)
    ok("B9 看图模式光标变手型", mv._cursor_kind == "point",
       f"kind={mv._cursor_kind} (before={kind_before})")

# ======================================================================
# C. 变异自检：把命中表掏空 ⇒ B3/B4/B7 必须全部失败
# ======================================================================
print("\n[C] 变异自检")
saved = mv._view_hit
mv._view_hit = []
m1 = mv.view_hit_station(QPointF(its[0].pos())) is None if its else False
calls.clear()
win._handle_hover_view_mode(QPointF(its[0].pos()) if its else far, vp)
m2 = len(calls) == 0
ok("C1 变异（清空命中表）判据会失败", m1 and m2, f"hit_none={m1} no_bubble={m2}")
mv._view_hit = saved

# 复原：退出看图模式
mv.exit_view_mode()
pump(6)
ok("C2 退出看图模式后命中表作废", not getattr(mv, "_view_hit", None))
ok("C3 退出后回到矢量模式", not mv._view_mode)

print(f"\n==== v2.7.18 探针：{N_OK} 通过 / {len(FAILS)} 失败 ====")
if FAILS:
    print("失败项：", FAILS)
sys.exit(1 if FAILS else 0)
