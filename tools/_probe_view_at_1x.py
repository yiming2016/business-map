# -*- coding: utf-8 -*-
"""只读诊断（v2.6.43）：最小缩放改成 1.0 之后，打开时视口里到底有没有东西。

背景：回归 `_chk_zoom_like_photo` 的 B4/C3（"缩放过程中画面有内容"）突然报
      非背景占比 0.000。两种可能：
        ① 真 bug（位图快照抓到空图）；
        ② 1.0 档下视口只覆盖全图的 1/9，中心恰好是空白区 ⇒ 抓的就是空白。
      这里直接量：初始视图 / 1.0 档 / 居中到某个站，三种情况下的墨迹占比。
"""
from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="view1x_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QPointF                                   # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402


def pump(n=6):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def ink(mv, frac=0.5):
    """中心 frac×frac 区域的非背景像素占比（粗采样）。"""
    vp = mv.viewport()
    vp.repaint()
    QApplication.processEvents()
    img = vp.grab().toImage()
    w, h = img.width(), img.height()
    x0, y0 = int(w * (1 - frac) / 2), int(h * (1 - frac) / 2)
    n = 0
    tot = 0
    for y in range(y0, y0 + int(h * frac), 3):
        for x in range(x0, x0 + int(w * frac), 3):
            tot += 1
            c = img.pixelColor(x, y)
            if not (abs(c.red() - 247) < 8 and abs(c.green() - 249) < 8
                    and abs(c.blue() - 251) < 8):
                n += 1
    return n / max(tot, 1) * 100.0


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(30)
    mv = win.map_view
    print(f"初始缩放 = {mv._scale:.3f}   （最小档 MIN_VIEW_SCALE="
          f"{__import__('ui.map_view', fromlist=['x']).MIN_VIEW_SCALE}）")
    print(f"初始视口中心墨迹占比：{ink(mv):.2f}%")

    for sc in (1.0, 2.0, 4.0):
        mv._zoom_anim.stop()
        if mv._zoom_snap is not None:
            mv._abort_zoom_snap()
        mv._apply_zoom_transform(sc / max(mv._scale, 1e-9),
                                 mv.viewport().rect().center())
        mv._sync_zoom_state()
        mv._apply_station_scale_all()
        mv._update_label_visibility()
        pump(8)
        print(f"  scale={sc:.2f}（视口中心不动）墨迹占比 {ink(mv):.2f}%")

    # 居中到一个站再看
    for it in mv.station_items.values():
        if it.data.get("station_name") == "车公庙":
            mv.centerOn(QPointF(it.pos().x(), it.pos().y()))
            pump(8)
            break
    print(f"居中到车公庙后（scale={mv._scale:.2f}）墨迹占比 {ink(mv):.2f}%")

    # 模拟回归的缩放序列：0.30 → 0.60 → 1.00 → 2.00 → 1.00，每步后量一次
    def set_scale(sc):
        mv._zoom_anim.stop()
        if mv._zoom_snap is not None:
            mv._abort_zoom_snap()
        mv._apply_zoom_transform(sc / max(mv._scale, 1e-9),
                                 mv.viewport().rect().center())
        mv._sync_zoom_state()
        mv._apply_station_scale_all()
        mv._update_label_visibility()
        pump(4)

    print("\n--- 模拟回归序列 ---")
    for sc in (0.30, 0.60, 1.00, 2.00, 1.00):
        set_scale(sc)
        c = mv.mapToScene(mv.viewport().rect().center())
        print(f"  scale={sc:.2f} 墨迹 {ink(mv):.2f}%  视口中心场景 "
              f"({c.x():.0f},{c.y():.0f})")
    # 附近有没有站点
    c = mv.mapToScene(mv.viewport().rect().center())
    near = [it.data.get("station_name") for it in mv.station_items.values()
            if abs(it.pos().x() - c.x()) < 300 and abs(it.pos().y() - c.y()) < 300]
    print(f"  视口中心 ±300 场景单位内的站：{near[:8]}（共 {len(near)} 个）")
    print(f"  站点质心 = {mv._station_centroid()}")

    r = mv.sceneRect()
    print(f"场景范围：{r.width():.0f}×{r.height():.0f}，视口 "
          f"{mv.viewport().width()}×{mv.viewport().height()}")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
