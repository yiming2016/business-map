"""
tools/_probe_v291.py —— v2.6.91 探针
T1 隐藏按钮在工具栏最右（豪宅/icon_panel 同行右侧），面板头部已去掉
T2 站名输入框 40% 定宽 + 🎯 定位按钮（信号、跳转 2.5×、闪烁）
T3 拖站"单步跳变否决"：一步 1000 场景单位被拒、一步 10 接受
"""
import os
import sys

os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QToolBar, QPushButton

app = QApplication(sys.argv)
from ui.main_window import MainWindow
from ui import metro_render as MR
from ui import map_view as MV

PASS = []

def ok(name, cond, extra=""):
    PASS.append(bool(cond))
    print(("PASS" if cond else "FAIL"), name, extra)

w = MainWindow()
w.resize(1480, 900)
w.show()
app.processEvents()

# ★★ v2.7.0 起启动**默认锁定轨迹**，T3 的拖动判据会被锁否决（不是产品问题）。
#    跟 _chk_label_lock_drag / _chk_click_no_save 一样，探针里先解开两把锁。
w._apply_lock_states(False, False)
app.processEvents()

# ---------- T1 隐藏按钮位置 ----------
tb = w.findChildren(QToolBar)[0]
acts = tb.actions()
idx_icon = idx_btn = None
widgets = []
for i, a in enumerate(acts):
    wa = tb.widgetForAction(a)
    if wa is w.map_view.icon_panel:
        idx_icon = i
    if wa is w.btn_info_toggle:
        idx_btn = i
    widgets.append(wa)
ok("T1a 按钮已进工具栏", idx_btn is not None)
ok("T1b 在 icon_panel(豪宅) 右侧", idx_icon is not None and idx_btn is not None
   and idx_btn > idx_icon, f"icon={idx_icon} btn={idx_btn} 总数={len(acts)}")
ok("T1c 是最后一个控件", idx_btn == len(acts) - 1)
ok("T1d 面板头部已去掉", w.info_wrap.layout().count() == 1)

# ---------- T2 站名 40% + 🎯 ----------
sid = next(iter(w.map_view.station_items))
w.info_panel.show_station(sid)
app.processEvents()
tw = w.info_panel.title.width()
ok("T2a 站名框已定宽", w.info_panel.title.maximumWidth() < 16777215, f"w={tw}")
ok("T2b 🎯 按钮存在", w.info_panel.btn_locate.isVisible() or not w.info_panel.btn_locate.isHidden())
# 点 🎯 → 定位（缩放 2.5 + 闪烁）
w.map_view.select_station(sid, emit=False)   # 先清状态
w.map_view.clear_selection()
app.processEvents()
fired = []
w.info_panel.locate_requested.connect(lambda s: fired.append(s))
w.map_view.blink_station(sid)                 # 占位：真实触发走 _locate_station
w.info_panel.btn_locate.click()
app.processEvents()
ok("T2c 🎯 发出信号", fired == [sid], f"{fired}")
# 走完整定位链路：倍数应为 2.5
w._locate_station(sid, "探针")
app.processEvents()
# ★ v2.7.0 起「2.5」指**面板显示的数字**：内部值 = 2.5 × ZOOM_BASE
#   （面板最小档 1.00× 对应内部 ZOOM_BASE，显示值 = 内部值 / ZOOM_BASE）。
_shown = w.map_view._scale / MV.ZOOM_BASE
ok("T2d 定位缩放=面板 2.5×", abs(_shown - 2.5) < 1e-6,
   f"显示={_shown:.3f} 内部={w.map_view._scale} base={MV.ZOOM_BASE}")
ok("T2e 闪烁已启动", w.map_view._blink_timer is not None)
w.map_view._stop_blink()

# ---------- T3 跳变否决 ----------
it = w.map_view.station_items[sid]
p0 = QPointF(it.pos())
it._press_pos = QPointF(p0)          # 模拟鼠标拖动中
it._drag_last_pos = QPointF(p0)
far = QPointF(p0.x() + 1000.0, p0.y() + 800.0)
ret = it.itemChange(MR.QGraphicsItem.GraphicsItemChange.ItemPositionChange, far)
ok("T3a 一步 1000+800 被否决", ret == p0, f"ret={ret}")
near = QPointF(p0.x() + 10.0, p0.y() - 6.0)
ret2 = it.itemChange(MR.QGraphicsItem.GraphicsItemChange.ItemPositionChange, near)
ok("T3b 一步 10/-6 接受", abs(ret2.x() - near.x()) < 1e-6, f"ret={ret2}")
ok("T3c 基准已前进", it._drag_last_pos == near)
# 程序化（非拖动）不受限
it._press_pos = None
it._drag_last_pos = None
ret3 = it.itemChange(MR.QGraphicsItem.GraphicsItemChange.ItemPositionChange, far)
ok("T3d 程序化 setPos 不受限", abs(ret3.x() - far.x()) < 1e-6)
# 还原
it.setPos(p0)
app.processEvents()

w.close()
app.processEvents()
print(f"TOTAL {sum(PASS)}/{len(PASS)}")
sys.exit(0 if all(PASS) else 1)
