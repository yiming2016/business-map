"""
tools/bench_pan.py
================================
拖拽平移性能基准测试。

模拟连续平移 150 帧，统计每帧耗时（毫秒）与等效帧率。

用法：
    python tools/bench_pan.py            # 测当前代码
    python tools/bench_pan.py --nocache  # 关掉离屏缓存，对照用
    python tools/bench_pan.py --old      # 模拟改造前（每帧重建文字轮廓）
"""

import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

NOCACHE = "--nocache" in sys.argv
OLD = "--old" in sys.argv

from PySide6.QtWidgets import QApplication              # noqa: E402
from PySide6.QtGui import QFont                          # noqa: E402
from PySide6.QtCore import Qt                            # noqa: E402

import ui.metro_render as mr                             # noqa: E402


if NOCACHE:
    mr.StationDotItem.setCacheMode = lambda self, m: None
    mr.HaloLabel.setCacheMode = lambda self, m: None

if OLD:
    def _slow_path(self):
        from PySide6.QtGui import QPainterPath, QFontMetricsF
        from PySide6.QtCore import QPointF
        p = QPainterPath()
        p.addText(QPointF(0.0, float(QFontMetricsF(self.font()).ascent())),
                  self.font(), self.text())
        return p
    mr.HaloLabel._text_path = _slow_path

from ui.map_view import MapView                            # noqa: E402
from core.data_manager import get_data_manager             # noqa: E402


def _arg(name, default):
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return float(sys.argv[i + 1])
    return default


def main():
    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)

    mv = MapView()
    mv.resize(1600, 900)
    # 让 Qt 照常渲染但不真的显示在屏幕上（否则测试完会弹一堆窗口）
    mv.setAttribute(Qt.WA_DontShowOnScreen, True)
    mv.show()

    dm = get_data_manager()
    mv.rebuild_lines()
    mv.reload_stations(dm.all_stations())
    app.processEvents()

    first = next(iter(mv.station_items))
    scale = _arg("--scale", 1.0)
    if scale <= 0:
        mv.fit_map()                    # 默认打开时的整图缩放
    else:
        mv.zoom_to_station(first, scale)
    app.processEvents()
    print(f"缩放 = {mv.transform().m11():.4f}")

    h = mv.horizontalScrollBar()
    v = mv.verticalScrollBar()
    print(f"滚动范围  x=[{h.minimum()},{h.maximum()}]  y=[{v.minimum()},{v.maximum()}]")

    vis_labels = sum(1 for it in mv.station_items.values() if it.label.isVisible())
    print(f"站点 {len(mv.station_items)}  线路 {len(mv.line_items)}  当前可见站名 {vis_labels}")

    # 预热
    for _ in range(10):
        h.setValue(h.value() + 20)
        mv.viewport().repaint()

    N = 150
    t0 = time.perf_counter()
    for i in range(N):
        hv = h.value() + 31
        if hv > h.maximum() - 40:
            hv = h.minimum() + 50
        vv = v.value() + 19
        if vv > v.maximum() - 40:
            vv = v.minimum() + 40
        h.setValue(hv)
        v.setValue(vv)
        mv.viewport().repaint()
    t1 = time.perf_counter()

    per = (t1 - t0) / N * 1000
    print(f"[结果] {N} 帧 {t1 - t0:.3f}s   平均 {per:.2f} ms/帧   ≈ {1000/per:.0f} FPS")


if __name__ == "__main__":
    main()
