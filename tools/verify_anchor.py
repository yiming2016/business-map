# -*- coding: utf-8 -*-
"""验证缩放锚点公式：MapView 手工公式 (scroll+vp)/scale 是否等于 Qt 自己的
mapToScene()。不一致 = 动画帧整体偏移（缩放时"错位"、停手后被拉回）。
"""
import os
import sys

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, QPointF

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
v.fit_map()
app.processEvents()

print(f"fit 后 scale={v._scale:.4f} viewport={v.viewport().width()}x{v.viewport().height()}")
print(f"scrollbar range: H={v.horizontalScrollBar().minimum()}..{v.horizontalScrollBar().maximum()} "
      f"V={v.verticalScrollBar().minimum()}..{v.verticalScrollBar().maximum()}")
print()

vp = QPoint(v.viewport().width() // 2, v.viewport().height() // 2)


def check(tag):
    h = v.horizontalScrollBar()
    vb = v.verticalScrollBar()
    s = v.transform().m11()
    manual = QPointF((h.value() + vp.x()) / s, (vb.value() + vp.y()) / s)
    real = v.mapToScene(vp)
    dx = manual.x() - real.x()
    dy = manual.y() - real.y()
    # 换算成屏幕像素误差
    px_err = (dx * dx + dy * dy) ** 0.5 * s
    print(f"{tag:>18s} scale={s:7.4f} Hrange={h.maximum() - h.minimum():6d} "
          f"manual=({manual.x():9.2f},{manual.y():9.2f}) real=({real.x():9.2f},{real.y():9.2f}) "
          f"误差={px_err:8.2f} 屏幕px")
    return px_err


errs = []
errs.append(check("fit状态"))

# 依次放大，每次用真实变换（与收尾一致）
for i in range(1, 13):
    v._apply_zoom_transform(1.25, anchor=QPointF(vp))
    app.processEvents()
    errs.append(check(f"放大{i}档"))

print("\n再缩放回去（模拟缩小到内容比窗口小）")
for i in range(1, 10):
    v._apply_zoom_transform(1 / 1.25, anchor=QPointF(vp))
    app.processEvents()
    errs.append(check(f"缩小{i}档"))

print(f"\n最大屏幕误差 = {max(errs):.2f} px  （>2px 就会肉眼可见错位）")
