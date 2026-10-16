# -*- coding: utf-8 -*-
"""sprite 渲染微基准：定位 render_sprite 1.6ms 的构成。"""
import os
import sys
import time

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from core.data_manager import get_data_manager
from ui.map_view import MapView

dm = get_data_manager()
v = MapView()
v.resize(1400, 900)
v.rebuild_lines()
v.reload_stations(dm.all_stations())
v.show()
app.processEvents()

items = list(v.station_items.values())
print("站点数", len(items))
# 取有站名的样本
sample = [it for it in items if it.is_label_visible()][:60]
print("有站名样本", len(sample))

N = 5


def bench(fn, label):
    for _ in range(2):
        fn()
    s = time.perf_counter()
    for _ in range(N):
        fn()
    dt = 1000 * (time.perf_counter() - s) / N
    print(f"{label}: {dt:.3f} ms/次")
    return dt


# 1. 完整 render_sprite
bench(lambda: [it.render_sprite(1.0) for it in sample], f"render_sprite ×{len(sample)}")

# 2. 只画圆点（跳过 label.paint）
from PySide6.QtGui import QPixmap, QPainter, QStyleOptionGraphicsItem
from PySide6.QtCore import Qt


def dot_only():
    for it in sample:
        br = it.boundingRect()
        w = br.width() * it._view_scale
        h = br.height() * it._view_scale
        if w <= 1 or h <= 1:
            continue
        pm = QPixmap(max(2, int(w)), max(2, int(h)))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.scale(it._view_scale, it._view_scale)
        p.translate(-br.left(), -br.top())
        it.paint(p, QStyleOptionGraphicsItem(), None)
        p.end()


bench(dot_only, f"仅圆点 layer ×{len(sample)}")

# 3. 只画站名（含描边）
def label_only():
    for it in sample:
        lab = it.label
        br = lab.boundingRect()
        pm = QPixmap(max(2, int(br.width()) + 4), max(2, int(br.height()) + 4))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        lab.paint(p, QStyleOptionGraphicsItem(), None)
        p.end()


bench(label_only, f"仅站名(描边) layer ×{len(sample)}")

# 4. QPixmap 分配 + QPainter 起停（空画）
def alloc_only():
    for it in sample:
        pm = QPixmap(120, 30)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.end()


bench(alloc_only, f"空 pixmap+painter ×{len(sample)}")

# 5. 文字路径构建（含 addText）
def path_build():
    for it in sample:
        it.label._path_cache = None
        it.label._text_path()


bench(path_build, f"文字轮廓路径重建 ×{len(sample)}")

# 6. 站名 paint 时描边开销：临时把 halo 设 0
for it in sample:
    it.label.set_halo_width(0.0)
bench(label_only, f"仅站名(无描边) ×{len(sample)}")
