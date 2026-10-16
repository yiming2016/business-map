"""缩放性能基准：测量平滑缩放动画期间每帧的真实重绘耗时。

用 viewport().render() 强制软件重绘（接近真实 paint 路径），
对比不同缓存策略下的帧耗时：
  A. 现状（站点/站名 DeviceCoordinateCache，缩放时每帧全部失效重建）
  B. 动画期间切 ItemCoordinateCache（位图随变换拉伸，零重建，轻微模糊）
  C. B + 动画期间跳过 _apply_line_width
用法: python tools/bench_zoom.py
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPixmap

from PySide6.QtWidgets import QGraphicsItem
from core.data_manager import get_data_manager
from ui.map_view import MapView
from ui.metro_render import StationDotItem

app = QApplication(sys.argv)
dm = get_data_manager()
v = MapView()
v.resize(1400, 900)
v.rebuild_lines()
v.reload_stations(dm.all_stations())
v.show()
app.processEvents()

h = v.horizontalScrollBar()
v.centerOn(QPointF(4000, 4300))
app.processEvents()
print(f"初始 scale={v._scale:.4f}  站点 {len(v.station_items)} 个  h range={h.maximum()}")


def bench(name, steps=12, ratio=1.06, setup=None, teardown=None):
    """每步：_apply_zoom_ratio + 强制重绘，取平均帧耗时。"""
    if setup:
        setup()
    pm = QPixmap(v.viewport().size())
    ts = []
    for i in range(steps):
        v._apply_zoom_ratio(ratio)
        t0 = time.perf_counter()
        pm.fill()
        v.viewport().render(pm)
        app.processEvents()
        ts.append(time.perf_counter() - t0)
    if teardown:
        teardown()
    avg = sum(ts) / len(ts) * 1000
    worst = max(ts) * 1000
    print(f"{name:<42s}  平均 {avg:6.1f} ms/帧   最差 {worst:6.1f} ms   (~{1000/avg:.0f} FPS)")
    return avg


# 回到基准状态
def reset():
    v.fit_map()
    v.centerOn(QPointF(4000, 4300))
    app.processEvents()


reset()

# A. 现状
bench("A. 现状: DeviceCoordinateCache(缩放即重建)", setup=reset)

# B. 动画期间切 ItemCoordinateCache
def switch_item_cache():
    for it in v.station_items.values():
        it.setCacheMode(QGraphicsItem.ItemCoordinateCache)
        it.label.setCacheMode(QGraphicsItem.ItemCoordinateCache)

def restore_device_cache():
    for it in v.station_items.values():
        it.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        it.label.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

bench("B. ItemCoordinateCache(缩放零重建)",
      setup=lambda: (reset(), switch_item_cache()),
      teardown=restore_device_cache)

# C. B + 跳过 line width
import ui.map_view as mv_mod
orig_lw = MapView._apply_line_width
def bench_c():
    MapView._apply_line_width = lambda self: None
    switch_item_cache()
def bench_c_teardown():
    MapView._apply_line_width = orig_lw
    restore_device_cache()

bench("C. ItemCache + 动画期跳过线宽更新",
      setup=lambda: (reset(), bench_c()),
      teardown=bench_c_teardown)

restore_device_cache()

# D. 动画期间隐藏站名（v2.4 实际方案）
def hide_labels():
    v._labels_hidden_for_zoom = False
    v._hide_labels_for_zoom()
def show_labels():
    v._labels_hidden_for_zoom = False
    for it in v.station_items.values():
        it.label.setVisible(True)

bench("D. 动画期隐藏站名(实际采用)", setup=lambda: (reset(), hide_labels()),
      teardown=show_labels)

show_labels()

# E. 快照拉伸：动画帧成本 = 一次锚点 blit
from PySide6.QtGui import QPainter as QP
def snap_begin():
    reset()
    v._zoom_snap = v.viewport().grab()
    v._snap_scale = v._scale
    v._snap_anchor = v._zoom_anchor.toPoint() if not v._zoom_anchor.isNull() else QPointF(700, 450)
def snap_frame():
    v._scale *= 1.06   # 只走变换数值 + 快照 blit（模拟动画帧）
    v._update_snap_pixmap()
bench("E. 快照拉伸动画帧(锚点blit)", steps=20,
      setup=snap_begin, teardown=lambda: setattr(v, "_zoom_snap", None))
v._zoom_snap = None
print("\n(结果说明：真实 GUI 还有合成/上屏开销，本测试为纯绘制成本；")
print(" 60fps 需 <16.7ms，丝滑感下限约 <20ms)")
