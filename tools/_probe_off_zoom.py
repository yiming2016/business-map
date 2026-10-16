# -*- coding: utf-8 -*-
"""只读诊断（v2.6.40）：**手动改过位置**的站名，缩放时会不会错位/消失。

用户原话：「修改过位置的站点文字，缩放的时候会导致错位或者直接不显示」

怀疑：手动偏移 `_label_off` 存的是**屏幕像素**（缩放时在屏幕上恒定），
      而 v2.6.38 把站名改成**等比**（框尺寸 = 30×scale）⇒ 两者量纲不一致：
      放大时字变大、偏移不变 ⇒ 字贴回圆点/压到线上 ⇒ 排版器判"压线"把它藏掉。
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

_TMP = Path(tempfile.mkdtemp(prefix="offzoom_"))
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


def pump(n=6):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def set_scale(mv, scale):
    mv._zoom_anim.stop()
    if mv._zoom_snap is not None:
        mv._abort_zoom_snap()
    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    mv._update_label_visibility()
    pump(5)


def drag(mv, it, dx=60, dy=-36):
    mv._zoom_anim.stop()
    if mv._zoom_snap is not None:
        mv._abort_zoom_snap()
    mv.centerOn(it.pos())
    pump(6)
    box = it.label_scene_rect()
    p = mv.mapFromScene(box.center())
    vp = mv.viewport()
    if not (0 <= p.x() < vp.width() and 0 <= p.y() < vp.height()):
        return False
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(p.x()), int(p.y())))
    pump(2)
    QTest.mouseMove(vp, QPoint(int(p.x()) + dx, int(p.y()) + dy))
    pump(2)
    QTest.mouseMove(vp, QPoint(int(p.x()) + dx + 10, int(p.y()) + dy + 6))
    pump(2)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier,
                       QPoint(int(p.x()) + dx + 10, int(p.y()) + dy + 6))
    pump(6)
    return True


def report(mv, it, tag):
    print(f"\n--- {tag} ---")
    print(f"{'缩放':>6}{'可见':>6}{'偏移(屏幕px)':>16}{'框宽(屏幕px)':>14}"
          f"{'字中心离圆点(屏幕px)':>22}")
    for sc in (0.30, 0.50, 1.00, 2.00):
        set_scale(mv, sc)
        vis = it.is_label_visible()
        box = it.label_scene_rect()
        cx = box.center().x() - it.pos().x()
        cy = box.center().y() - it.pos().y()
        print(f"{sc:>6.2f}{('是' if vis else '★否'):>6}"
              f"{'(' + format(it.label_off().x(), '.0f') + ',' + format(it.label_off().y(), '.0f') + ')':>16}"
              f"{box.width() * sc:>14.1f}"
              f"{'(' + format(cx * sc, '.0f') + ',' + format(cy * sc, '.0f') + ')':>22}")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(20)
    mv = win.map_view

    tgt = None
    for it in mv.station_items.values():
        if it.data.get("station_name") == "车公庙":
            tgt = it
            break
    tgt = tgt or list(mv.station_items.values())[0]
    print(f"测试站：{tgt.data.get('station_name')}")

    report(mv, tgt, "拖之前（自动摆位）")
    if not drag(mv, tgt):
        print("（站名不在视口，拖不了）")
    else:
        print(f"\n拖完：label_off = ({tgt.label_off().x():.0f}, "
              f"{tgt.label_off().y():.0f})")
        report(mv, tgt, "拖之后（手动改过位置）")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
