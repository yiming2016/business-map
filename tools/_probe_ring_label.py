# -*- coding: utf-8 -*-
"""只读诊断（v2.6.39）：转弯处 / 被外推的站名，拖了有没有反应？

怀疑：`_label_box()` 里手动偏移只在 **ring==0** 那一层叠加 ——
      排版器为了躲线路会把站名推到外圈（side 带 ring>0，如 'right1'），
      而拐弯处线路最密、最容易被推 ⇒ 这类站名**拖了纹丝不动**。

做法：列出所有 ring>0 的站，挑几个真按真拖一次，看 label_off 变没变。
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

_TMP = Path(tempfile.mkdtemp(prefix="ringprobe_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QPoint, Qt                                # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402
from ui.metro_render import split_label_ring                        # noqa: E402


def pump(n=8):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def drag_label(mv, it):
    mv._zoom_anim.stop()
    mv._abort_zoom_snap() if mv._zoom_snap is not None else None
    mv.centerOn(it.pos())
    pump(8)
    lr = it.label_scene_rect()
    p = mv.mapFromScene(lr.center())
    vp = mv.viewport()
    if not (0 <= p.x() < vp.width() and 0 <= p.y() < vp.height()):
        return None
    before = (it.label_off().x(), it.label_off().y())
    box0 = it.label_scene_rect()          # ★ 屏幕/场景里**真正绘制**的位置
    hit = mv._label_hit(lr.center())
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(p.x()), int(p.y())))
    pump(2)
    grabbed = mv._drag_label is not None and mv._drag_label["item"] is it
    QTest.mouseMove(vp, QPoint(int(p.x()) + 50, int(p.y()) - 30))
    pump(2)
    QTest.mouseMove(vp, QPoint(int(p.x()) + 60, int(p.y()) - 36))
    pump(2)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier,
                       QPoint(int(p.x()) + 60, int(p.y()) - 36))
    pump(6)
    after = (it.label_off().x(), it.label_off().y())
    box1 = it.label_scene_rect()
    dbox = abs(box1.x() - box0.x()) + abs(box1.y() - box0.y())
    return grabbed, before, after, dbox


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(20)
    mv = win.map_view

    ringed, flat = [], []
    for it in mv.station_items.values():
        ring = split_label_ring(it.label_side())[1]
        (ringed if ring > 0 else flat).append(it)
    print(f"主站体 {len(mv.station_items)} 个："
          f"站名被外推(ring>0) {len(ringed)} 个，贴着圆点(ring=0) {len(flat)} 个")
    print("\nring>0 的例子：")
    for it in ringed[:10]:
        print(f"   {it.data.get('station_name'):<8} side={it.label_side():<8} "
              f"线路={','.join((it.data.get('lines') or [])[:4])}")

    print("\n实测拖动（ring>0 的前 6 个）：")
    for it in ringed[:6]:
        r = drag_label(mv, it)
        if r is None:
            print(f"   {it.data.get('station_name'):<8} （站名不在视口内，跳过）")
            continue
        grabbed, b, a, dbox = r
        moved = abs(a[0] - b[0]) + abs(a[1] - b[1])
        print(f"   {it.data.get('station_name'):<8} side={it.label_side():<8} "
              f"抓住={grabbed}  偏移变={moved:.0f}  ★实际位置移动={dbox:.1f} "
              f"{'❌拖了不动' if dbox < 5 else 'OK'}")

    print("\n对照组（ring=0 的前 3 个）：")
    for it in flat[:3]:
        r = drag_label(mv, it)
        if r is None:
            continue
        grabbed, b, a, dbox = r
        moved = abs(a[0] - b[0]) + abs(a[1] - b[1])
        print(f"   {it.data.get('station_name'):<8} side={it.label_side():<8} "
              f"抓住={grabbed}  偏移变={moved:.0f}  ★实际位置移动={dbox:.1f} "
              f"{'❌拖了不动' if dbox < 5 else 'OK'}")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
