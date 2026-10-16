# -*- coding: utf-8 -*-
"""v2.7.16 离屏探针（offscreen，绝不弹窗）。

三条改动：
  ① 「✳ 添加模式」删除，「➕ 新建站点」变成**可勾选开关**
     （老 `_on_add_station_toolbar` 干的事就是把它 setChecked(True)——真重复）；
  ② 居中 / 适配窗口 / 定位站点一律按**可见区**（扣掉左右浮层），
     不再把目标摆到面板底下；
  ③ 拖宽把手改挂 map_area（浮层同级）并 raise 到最上层 ——
     修「光标贴到边缘了却不出现拉伸箭头」。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtCore import QPoint                               # noqa: E402
from PySide6.QtWidgets import QApplication                      # noqa: E402
from PySide6.QtTest import QTest                                # noqa: E402

app = QApplication(sys.argv)
from ui.main_window import MainWindow, LEGEND_MIN_W, INFO_PANEL_MIN_W  # noqa: E402

PASS = FAIL = 0
FAILED = []


def ok(name, cond, info=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}" + (f"  ({info})" if info else ""))
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  ✗ {name}  —— {info}")


def pump(n=12):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


win = MainWindow()
win.resize(1600, 900)
win.show()
pump(20)
mv = win.map_view
win._view_autostart_done = True

print("===== ① 「添加模式」已删，「新建站点」是开关 =====")
names = [a.text() for a in getattr(win, "_edit_actions", [])]
ok("①-1 编辑按钮里再没有「添加模式」", not any("添加模式" in t for t in names),
   " / ".join(names))
ok("①-2 「新建站点」还在", any("新建站点" in t for t in names))
act = getattr(win, "act_new_station", None)
ok("①-3 act_new_station 存在且可勾选", act is not None and act.isCheckable())
sc = [s.toString() for s in act.shortcuts()] if act is not None else []
ok("①-4 Ctrl+N / Ctrl+M 两个快捷键都还在", "Ctrl+N" in sc and "Ctrl+M" in sc,
   ",".join(sc))
act.setChecked(True)
pump(6)
on = mv.add_mode if hasattr(mv, "add_mode") else getattr(mv, "_add_mode", None)
ok("①-5 勾上 = 真的进入添加模式", bool(on), f"map_view.add_mode={on}")
ok("①-6 勾上后按钮自己就是高亮状态", act.isChecked())
act.setChecked(False)
pump(6)
off = mv.add_mode if hasattr(mv, "add_mode") else getattr(mv, "_add_mode", None)
ok("①-7 取消 = 退出添加模式", not off, f"map_view.add_mode={off}")

print("===== ② 居中 / 定位按「可见区」（扣除左右浮层） =====")
# 两个浮层都打开
try:
    if not win.legend_panel.isVisible():
        win._on_toggle_legend(True)
    if not win.info_panel.isVisible():
        win._on_toggle_info_panel()
except Exception as e:
    print("      （开面板异常：", repr(e), "）")
pump(12)
lw = win.legend_panel.width()
iw = win.info_wrap.width()
ok("②-1 左浮层宽度已写给地图", abs(mv._inset_l - lw) <= 1, f"inset_l={mv._inset_l} / {lw}")
ok("②-2 右浮层宽度已写给地图", abs(mv._inset_r - iw) <= 1, f"inset_r={mv._inset_r} / {iw}")
vpw = mv.viewport().width()
vis = mv.visible_viewport_rect()
ok("②-3 可见区 = 视口去掉两侧浮层", abs(vis.width() - (vpw - lw - iw)) <= 2,
   f"可见 {vis.width()} / 应 {vpw - lw - iw}")

sid = next(iter(mv.station_items))
mv.zoom_to_station(sid, 2.5)
pump(20)
p = mv.mapFromScene(mv.station_items[sid].pos())
ok("②-4 定位后站点落在**可见区**里（没被右侧面板盖住）",
   vis.left() <= p.x() <= vis.right(),
   f"站点 x={p.x()} / 可见区 {vis.left()}..{vis.right()}（面板占 {vis.right()}..{vpw}）")
ok("②-5 定位后站点≈可见区正中（±25px）",
   abs(p.x() - vis.center().x()) <= 25,
   f"站点 x={p.x()} / 可见区中心 {vis.center().x()} / 视口中心 {vpw//2}")

# 适配窗口：整张内容应落在可见区内
mv.fit_map()
pump(20)
base = mv._content_rect
tl = mv.mapFromScene(base.topLeft())
br = mv.mapFromScene(base.bottomRight())
w_content = br.x() - tl.x()
ok("②-6 适配窗口按**可见区宽度**算（内容屏幕宽≈可见区宽，不是整块视口）",
   abs(w_content - vis.width()) <= 20,
   f"内容宽 {w_content:.0f} / 可见区 {vis.width()} / 视口 {vpw}")

# 关掉右面板 ⇒ inset 归零
win._on_toggle_info_panel()
pump(12)
ok("②-7 收起右面板后 inset_r 归零", mv._inset_r == 0, f"inset_r={mv._inset_r}")
win._on_toggle_info_panel()
pump(12)

print("===== ③ 拖宽把手：热区在最上层（贴边就该出现拉伸箭头） =====")
lg = getattr(win, "legend_grip", None)
ig = getattr(win, "info_grip", None)
ok("③-1 两个把手都挂到 map_area（浮层同级，不被内容盖住）",
   lg is not None and ig is not None
   and lg.parent() is win.map_area and ig.parent() is win.map_area,
   f"legend.parent={type(lg.parent()).__name__ if lg else None}")
ok("③-2 把手可见", lg.isVisible() and ig.isVisible())
ok("③-3 左把手贴着图例右缘内侧", abs(lg.x() + lg.width() - lw) <= 1,
   f"把手右缘 {lg.x()+lg.width()} / 图例宽 {lw}")
ok("③-4 右把手贴着详情面板左缘内侧", abs(ig.x() - (win.map_area.width() - iw)) <= 1,
   f"把手 x={ig.x()} / 面板左缘 {win.map_area.width()-iw}")


def top_child_at(widget, x, y):
    """该点最上层的子控件是谁（决定光标形状归谁管）。"""
    return widget.childAt(QPoint(x, y))


# ★ 判据的核心：鼠标落在把手中心时，最上层子控件**必须是把手**
#   （旧实现挂在浮层里、被 InfoPanel 盖住 ⇒ 这里会拿到别的东西 ⇒ 光标不变）
c_lg = top_child_at(win.map_area, lg.x() + lg.width() // 2, 300)
ok("③-5 左把手位置最上层就是把手（不被图例内容盖住）", c_lg is lg,
   f"取到 {type(c_lg).__name__ if c_lg else None}")
c_ig = top_child_at(win.map_area, ig.x() + ig.width() // 2, 300)
ok("③-6 右把手位置最上层就是把手（不被详情面板盖住）", c_ig is ig,
   f"取到 {type(c_ig).__name__ if c_ig else None}")
ok("③-7 把手光标 = 左右拉伸箭头", "SplitHCursor" in str(lg.cursor().shape()),
   str(lg.cursor().shape()))

print("===== ④ 变异自检：把手退回浮层内部 ⇒ 热区立刻失效 =====")
old_parent = ig.parent()
ig.setParent(win.info_wrap)          # 退回旧写法（挂在浮层里）
ig.setGeometry(0, 0, ig.width(), win.info_wrap.height())
pump(6)
c_bad = top_child_at(win.info_wrap, ig.width() // 2, 300)
ok("④-1 把手退回浮层内部后，最上层不再是把手（证明 ③-6 判据真抓得住）",
   c_bad is not ig, f"取到 {type(c_bad).__name__ if c_bad else None}")
ig.setParent(old_parent)             # 复原
win._layout_overlays()
pump(6)
c_ok = top_child_at(win.map_area, ig.x() + ig.width() // 2, 300)
ok("④-2 复原后热区又是把手", c_ok is ig,
   f"取到 {type(c_ok).__name__ if c_ok else None}")

print("===== ⑤ 拖把手仍能改宽度（没被改坏） =====")
w0 = win.info_wrap.width()
cap = win._overlay_width_cap()
win._set_info_w(cap + 300)          # 想拖到天上
pump(8)
ok("⑤-1 拖宽有封顶（不会拖过头）", win.info_wrap.width() <= cap + 2,
   f"{win.info_wrap.width()} / 上限 {cap}（离屏屏宽小，上限=屏宽55%）")
win._set_info_w(max(INFO_PANEL_MIN_W + 20, w0 - 60))
pump(8)
ok("⑤-1b 拖窄生效", win.info_wrap.width() < w0,
   f"{w0} → {win.info_wrap.width()}")
win._set_info_w(10)
pump(8)
ok("⑤-2 有下限（不至于拖没）", win.info_wrap.width() >= INFO_PANEL_MIN_W - 2,
   f"{win.info_wrap.width()} (下限 {INFO_PANEL_MIN_W})")
win._set_info_w(520)
pump(8)
ok("⑤-3 把手跟着面板走", abs(ig.x() - (win.map_area.width() - win.info_wrap.width())) <= 1,
   f"把手 x={ig.x()}")

print(f"\n===== 结果：{PASS} 通过 / {FAIL} 失败 =====")
if FAILED:
    print("失败项：")
    for n in FAILED:
        print("  -", n)
sys.exit(1 if FAIL else 0)
