# -*- coding: utf-8 -*-
"""只读诊断（v2.6.37）：对指定站的**站名**做一次真按真拖，看偏移到底有没有变。

跟 _probe_label_hit.py 的区别：那个只算"命中谁"，这个是真的发鼠标事件、
真的看 `label_off()` 有没有被改 —— 直接对应用户原话「拖不动」。
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

_TMP = Path(tempfile.mkdtemp(prefix="dragprobe_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import Qt, QPoint                            # noqa: E402
from PySide6.QtWidgets import QApplication                      # noqa: E402
from PySide6.QtTest import QTest                                # noqa: E402
from ui.main_window import MainWindow                           # noqa: E402


def pump(n=8):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def try_drag(mv, it, scale=None):
    if scale is not None:
        mv._zoom_anim.stop()
        mv._abort_zoom_snap()
        mv.set_scale(scale) if hasattr(mv, "set_scale") else None
        pump(6)
    mv._zoom_anim.stop()
    mv._abort_zoom_snap()
    mv.centerOn(it.pos())
    pump(8)

    lr = it.label_scene_rect()
    c = lr.center()
    vp = mv.viewport()
    p = mv.mapFromScene(c)
    if not (0 <= p.x() < vp.width() and 0 <= p.y() < vp.height()):
        return "offscreen", 0.0, 0.0
    hit = mv.station_at(c)
    hit_name = None if hit is None else hit.data.get("station_name")

    before = (it.label_off().x(), it.label_off().y())
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(int(p.x()), int(p.y())))
    pump(2)
    grabbed = mv._drag_label is not None
    grabbed_self = grabbed and mv._drag_label["item"] is it
    QTest.mouseMove(vp, QPoint(int(p.x()) + 40, int(p.y()) - 24))
    pump(2)
    QTest.mouseMove(vp, QPoint(int(p.x()) + 60, int(p.y()) - 36))
    pump(2)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier,
                       QPoint(int(p.x()) + 60, int(p.y()) - 36))
    pump(6)
    after = (it.label_off().x(), it.label_off().y())
    d = (after[0] - before[0], after[1] - before[1])
    return ("OK" if grabbed_self else ("没抓住" if not grabbed else "抓成别站")), d, hit_name


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(10)
    mv = win.map_view

    names = ["下沙", "后海", "科苑", "市民中心", "龙华", "观澜", "车公庙", "深圳北站"]
    by_name = {}
    for it in list(mv.station_items.values()) + list(mv.alt_items.values()):
        by_name.setdefault(it.data.get("station_name"), it)

    for sc in (None, 0.5):
        print(f"\n===== 缩放 {'(默认)' if sc is None else sc} =====")
        print(f"{'站名':<8}{'结果':<10}{'命中':<10}{'Δ偏移(屏幕px)':<20}")
        for nm in names:
            it = by_name.get(nm)
            if it is None:
                print(f"{nm:<8}（找不到这个站）")
                continue
            r, d, hit = try_drag(mv, it, sc)
            print(f"{nm:<8}{r:<10}{str(hit):<10}({d[0]:.1f}, {d[1]:.1f})")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
