# -*- coding: utf-8 -*-
"""把指定的几段换乘对放大截图，拼成一张图。

用法：
    python tools/_shot_trpair_zoom.py
产物：logs/_trpair_zoom.png
"""
import json
import sys
import tempfile
import shutil
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="trzoom_"))
for _n in ("stations.json", "lines.json", "underlay.png", "trace_cloud.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QFont    # noqa: E402
from PySide6.QtCore import QPointF, QRect, Qt                       # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402
from ui.map_view import line_station_xy                             # noqa: E402

LOGS = ROOT / "logs"
CELL = 430
COLS = 3
ZOOM = 3.4

import os

# 覆盖比最高的几段（修复前 0.90~0.94 = 只剩十几像素自由段）
CASES = [
    ("12", "国展", "国展北"),
    ("13", "后海", "科苑"),
    ("7", "八卦岭", "红岭北"),
    ("3", "红岭", "老街"),
    ("4", "深圳北站", "红山"),
    ("10", "莲花村", "岗厦北"),
    ("1", "购物公园", "会展中心"),
    ("13", "粤海门", "深大"),
    ("3", "华新", "通新岭"),
]
_SUF = "_old" if os.environ.get("METROEDITOR_STUB_FRAC") == "1.0" else ""


def pump(n=6):
    for _ in range(n):
        QTest.qWait(8)
        QApplication.processEvents()


def set_scale(mv, scale):
    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    pump(6)
    mv._invalidate_nn()
    mv._update_label_visibility()
    pump(8)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(10)
    mv = win.map_view
    st = CDM.get_data_manager().all_stations()

    set_scale(mv, 1.0)
    rows = int(math.ceil(len(CASES) / float(COLS)))
    sheet = QPixmap(CELL * COLS, CELL * rows + 22 * rows)
    sheet.fill(QColor("#F7F9FB"))
    sp = QPainter(sheet)
    sp.setRenderHint(QPainter.Antialiasing, True)
    f = QFont("Microsoft YaHei")
    f.setPixelSize(15)
    f.setBold(True)
    sp.setFont(f)

    for k, (lid, a, b) in enumerate(CASES):
        sa, sb = st.get(a), st.get(b)
        if not sa or not sb:
            print("跳过", lid, a, b)
            continue
        ax, ay = line_station_xy(sa, lid)
        bx, by = line_station_xy(sb, lid)
        mx, my = (ax + bx) * 0.5, (ay + by) * 0.5
        L = math.hypot(bx - ax, by - ay)
        mv.centerOn(QPointF(mx, my))
        pump(6)
        pm = mv.grab()
        p0 = mv.mapFromScene(QPointF(mx, my))
        p1 = mv.mapFromScene(QPointF(mx + (bx - ax), my + (by - ay)))
        vs = math.hypot(p1.x() - p0.x(), p1.y() - p0.y()) / max(L, 1e-6)
        side = int(max(L * vs * ZOOM, 200))
        rect = QRect(int(p0.x() - side // 2), int(p0.y() - side // 2), side, side)
        r = k // COLS
        c = k % COLS
        x0 = c * CELL
        y0 = r * (CELL + 22)
        crop = pm.copy(rect)
        if crop.isNull():
            print("裁剪越界", lid, a, b)
        else:
            sc = crop.scaled(CELL, CELL, Qt.KeepAspectRatio,
                             Qt.SmoothTransformation)
            sp.drawPixmap(x0 + (CELL - sc.width()) // 2,
                          y0 + (CELL - sc.height()) // 2, sc)
        sp.setPen(QPen(QColor("#B4232A")))
        sp.drawRect(x0, y0, CELL - 1, CELL - 1)
        sp.drawText(x0 + 6, y0 + CELL + 16, "%s  %s→%s" % (lid, a, b))
    sp.end()
    out = LOGS / ("_trpair_zoom%s.png" % _SUF)
    sheet.save(str(out))
    print("大图", out, sheet.width(), sheet.height())
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
