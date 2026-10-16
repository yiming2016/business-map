"""缓存模式渲染一致性测试：验证 ItemCoordinateCache（纹理化，GPU 模式使用）
与 DeviceCoordinateCache（CPU 模式使用）渲染出的像素位置是否一致。

若不一致 = 纹理化引入了"站名错位"bug，输出偏移量。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsScene
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QColor

app = QApplication(sys.argv)

from core.data_manager import get_data_manager
from ui.map_view import MapView

dm = get_data_manager()


def render(scale, mode, path):
    """mode: 'device' | 'item' —— 渲染整图到 PNG。"""
    v = MapView()
    v.resize(1400, 900)
    v.rebuild_lines()
    v.reload_stations(dm.all_stations())   # 内部会 fit_map + apply_view_scale
    for it in v.station_items.values():
        it._gpu_cache = (mode == "item")
    v.show()
    app.processEvents()
    # 设定目标缩放并居中
    v.resetTransform()
    v.scale(scale, scale)
    v._scale = scale
    v._apply_line_width()
    v._apply_station_scale_all()
    v.centerOn(QPointF(4000, 4300))
    app.processEvents()
    pm = v.viewport().grab()
    pm.save(path)
    v.close()
    return pm


def diff_image(pm_a, pm_b, thresh=24, path=None):
    """生成差异可视化：白底，差异像素按偏差强度画红。返回差异像素数、质心、最大偏差。"""
    a = pm_a.toImage().convertToFormat(QImage.Format_RGB32)
    b = pm_b.toImage().convertToFormat(QImage.Format_RGB32)
    w, h = min(a.width(), b.width()), min(a.height(), b.height())
    out = QImage(w, h, QImage.Format_RGB32)
    out.fill(0xFFFFFFFF)
    n = 0
    sx = sy = 0
    maxd = 0
    for y in range(0, h):
        for x in range(0, w):
            pa = a.pixelColor(x, y)
            pb = b.pixelColor(x, y)
            d = abs(pa.red() - pb.red()) + abs(pa.green() - pb.green()) + abs(pa.blue() - pb.blue())
            if d > thresh:
                n += 1
                sx += x
                sy += y
                maxd = max(maxd, d)
                inten = min(255, d)
                out.setPixelColor(x, y, QColor(255, 255 - inten // 2, 255 - inten // 2))
    if path:
        out.save(path)
    return n, (sx / n if n else 0), (sy / n if n else 0), maxd


def crop_save(pm, cx, cy, half, path):
    """从 pixmap 裁一个局部区域保存（用于肉眼对比文字是否错位）。"""
    img = pm.toImage().convertToFormat(QImage.Format_RGB32)
    x0 = max(0, cx - half)
    y0 = max(0, cy - half)
    w = min(img.width() - x0, half * 2)
    h = min(img.height() - y0, half * 2)
    img.copy(x0, y0, w, h).scaled(QSize(w * 3, h * 3), Qt.IgnoreAspectRatio, Qt.FastTransformation).save(path)


for scale in (0.1273, 0.30):
    pa = render(scale, "device", f"_diff_dev_{scale}.png")
    pb = render(scale, "item", f"_diff_item_{scale}.png")
    n, cx, cy, maxd = diff_image(pa, pb, path=f"_diff_heat_{scale}.png")
    total = pa.width() * pa.height()
    print(f"scale={scale}: 差异像素 {n}/{total} ({100*n/total:.1f}%)  差异质心 ({cx:.0f},{cy:.0f})  最大偏差 {maxd}")
    # 裁差异质心附近和图中心附近的局部放大图，肉眼对比
    for i, (qx, qy) in enumerate(((int(cx), int(cy)), (pa.width() // 2, pa.height() // 2))):
        crop_save(pa, qx, qy, 120, f"_diff_crop{i}_dev_{scale}.png")
        crop_save(pb, qx, qy, 120, f"_diff_crop{i}_item_{scale}.png")
print("输出: _diff_heat_*.png(差异热力图) / _diff_crop*_dev|item_*.png(局部3x放大对比)")
