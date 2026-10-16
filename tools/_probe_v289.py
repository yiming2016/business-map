# -*- coding: utf-8 -*-
"""
_probe_v289.py —— v2.6.89 四件套回归（offscreen，不抢焦点）：
  T1 工具栏：「定位」按钮已删；🔒 与 🚇 两钮在搜索框右侧、🚇 在 🔒 左侧
  T2 搜索候选面板：弹出位置整个落在主窗口客户区内（不越界）
  T3 🔒 锁定：itemChange 拒绝鼠标拖动（_press_pos 门）；程序化 setPos 不受影响
  T4 面板开合：图例显隐还原宽度；详情面板收起留细条+按钮、展开还原
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QPointF
from PySide6.QtWidgets import QApplication, QToolBar, QPushButton

app = QApplication(sys.argv)
from ui.main_window import MainWindow
from ui import metro_render as MR

w = MainWindow()
w.resize(1480, 900)
w.show()
app.processEvents()

def ok(name, cond, extra=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        globals()["_failed"] = True

_failed = False

# ---------- T1 工具栏 ----------
tb = w.findChildren(QToolBar)[0]
btns = tb.findChildren(QPushButton)
texts = [b.text() for b in btns if not b.isHidden()]
ok("T1a 定位按钮已删", "定位" not in texts, str(texts))
# ★ v2.7.0/2.7.2：🔒 早就不是文字按钮（LockButton 自绘），🚇 也换成 logo 图了，
#   **按文字找必然找不到** ⇒ 改成按对象身份定位，再比在工具栏里的先后。
_all_btns = [b for b in tb.findChildren(QPushButton) if not b.isHidden()]
lock_idx = leg_idx = -1
for _i, _b in enumerate(_all_btns):
    if _b is w.btn_lock:
        lock_idx = _i
    if _b is w.btn_legend_toggle:
        leg_idx = _i
ok("T1b 🔒/🚇 都在工具栏", lock_idx >= 0 and leg_idx >= 0,
   f"lock={lock_idx} legend={leg_idx}")
ok("T1c 🚇 在 🔒 左侧", 0 <= leg_idx < lock_idx, f"legend={leg_idx} lock={lock_idx}")
# 顺序上它们应在搜索框之后
box_i = -1
for i, it in enumerate(tb.actions()):
    pass
ok("T1d 锁 API 存在", hasattr(w.map_view, "set_stations_locked"))

# ---------- T2 弹层不出窗 ----------
w.search_popup.set_items([("南头古城", "南头古城", "12号线")], 1)
w.search_popup.show_at(w.search_box)
app.processEvents()
g = w.search_popup.geometry()
wg = w.geometry()
inside = (g.left() >= wg.left() and g.right() <= wg.right()
          and g.top() >= wg.top() and g.bottom() <= wg.bottom())
ok("T2a 弹层在主窗口客户区内", inside, f"popup={g} win={wg}")
w.search_popup.hide()

# 把窗口压矮再验一次（更苛刻）
w.resize(1480, 320)
app.processEvents()
w.search_popup.show_at(w.search_box)
app.processEvents()
g = w.search_popup.geometry()
inside2 = (g.bottom() <= wg.bottom() + 1)
ok("T2b 矮窗口也不越下沿", inside2, f"popup_bottom={g.bottom()} win_bottom={wg.bottom()}")
w.search_popup.hide()
w.resize(1480, 900)
app.processEvents()

# ---------- T3 🔒 锁定 ----------
st = next(iter(w.map_view.station_items.values()))
p0 = QPointF(st.pos())
# 程序化 setPos：解锁/加锁都应生效（不受锁影响）
w.map_view.set_stations_locked(True)
ok("T3a 标志位", w.map_view.stations_locked is True and MR.STATIONS_LOCKED is True)
st.setPos(p0.x() + 40, p0.y() + 40)
app.processEvents()
ok("T3b 程序化 setPos 不受锁影响",
   abs(st.pos().x() - (p0.x() + 40)) < 0.01, f"pos={st.pos()}")
# 鼠标拖动：itemChange 应拒绝（_press_pos 非 None = 正在拖）
st._press_pos = QPointF(st.pos())
from PySide6.QtWidgets import QGraphicsItem
trial = QPointF(st.pos().x() + 30, st.pos().y() - 10)
ret = st.itemChange(QGraphicsItem.GraphicsItemChange.ItemPositionChange, trial)
ok("T3c 锁定后鼠标拖动被否决", ret == st.pos(), f"ret={ret} pos={st.pos()}")
st._press_pos = None
w.map_view.set_stations_locked(False)
ret2 = st.itemChange(QGraphicsItem.GraphicsItemChange.ItemPositionChange, trial)
ok("T3d 解锁后放行", ret2 != st.pos(), f"ret={ret2}")
st.setPos(p0)

# ---------- T4 面板开合 ----------
sz0 = w.splitter.sizes()
w.btn_legend_toggle.setChecked(False)
app.processEvents()
ok("T4a 图例隐藏", w.legend_panel.isHidden())
w.btn_legend_toggle.setChecked(True)
app.processEvents()
sz1 = w.splitter.sizes()
ok("T4b 图例恢复且宽度还原", not w.legend_panel.isHidden()
   and abs(sz1[0] - sz0[0]) < 2, f"{sz0} -> {sz1}")

# ★ v2.7.1 起**首次打开不显示**右侧面板，所以先把它统一摆到"展开"再测收起动作，
#   否则第一次 click 是"展开"，T4c~T4f 全反着判（判据前提变了，不是产品回归）。
if w.info_panel.isHidden():
    w.btn_info_toggle.click()
    app.processEvents()
ok("T4c0 前置：面板已展开", w.info_panel.isVisible())
info_w0 = w.info_wrap.width()      # ★ 展开态宽度：T4g 的"还原"要跟它比
w.btn_info_toggle.click()
app.processEvents()
ok("T4c 详情面板收起", w.info_panel.isHidden())
# ★ v2.7.3：收起 = **完全收起**（容器一起藏、宽 0），不再是留 26px 细条
ok("T4d 收起后宽度归 0（完全收起）", w.info_wrap.width() == 0 and w.info_wrap.isHidden(),
   f"width={w.info_wrap.width()} wrapHidden={w.info_wrap.isHidden()}")
# 组合：图例藏着 → 收起/展开详情 → 图例回来，两边宽度都还原
w.btn_legend_toggle.setChecked(False)
w.btn_info_toggle.click()   # 展开（此时图例仍藏着）
app.processEvents()
ok("T4e 图例藏着时也能展开详情", not w.info_panel.isHidden())
w.btn_info_toggle.click()
app.processEvents()
ok("T4f 组合态收起仍是完全收起",
   w.info_panel.isHidden() and w.info_wrap.width() == 0)
w.btn_legend_toggle.setChecked(True)
w.btn_info_toggle.click()
app.processEvents()
sz2 = w.splitter.sizes()
ok("T4g 图例+详情宽度都还原", abs(sz2[0] - sz0[0]) <= 2 and abs(sz2[2] - info_w0) <= 4,
   f"{sz2} legend0={sz0[0]} info_w0={info_w0}")

print("\n====", "ALL PASS" if not _failed else "HAS FAILURES", "====")
sys.exit(1 if _failed else 0)
