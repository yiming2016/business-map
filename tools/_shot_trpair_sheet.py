# -*- coding: utf-8 -*-
"""把「相邻两站都是换乘站」的所有段拼成一张接触印相图，一次看全。

用户原话：「在两站都是换乘站的情况下，线路的轨道会出现严重变形」。
逐张 Read 太贵 ⇒ 自动枚举所有这种段，按段长裁剪局部、等比缩到 250×250，
拼成 8 列的网格大图。

用法：
    python tools/_shot_trpair_sheet.py
产物：logs/_trpair_sheet.png（大图）+ logs/_trpair_sheet.txt（每格是哪段）
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

_TMP = Path(tempfile.mkdtemp(prefix="trpair_"))
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
LOGS.mkdir(exist_ok=True)

CELL = 250
COLS = 8


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
    dm = CDM.get_data_manager()
    st = dm.all_stations()
    lj = json.loads((CDM.DATA_DIR / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj

    cases = []
    for L in lines:
        lid = str(L.get("id"))
        seq = [n for n in (L.get("stations") or []) if n in st]
        for i in range(1, len(seq)):
            a, b = seq[i - 1], seq[i]
            ta = len((st.get(a) or {}).get("lines") or []) > 1
            tb = len((st.get(b) or {}).get("lines") or []) > 1
            if ta and tb:
                cases.append((lid, a, b))
    print("「两站都是换乘站」的段共 %d 个" % len(cases))

    set_scale(mv, 1.0)
    rows = int(math.ceil(len(cases) / float(COLS)))
    sheet = QPixmap(CELL * COLS, CELL * rows + 22 * rows)
    sheet.fill(QColor("#F7F9FB"))
    sp = QPainter(sheet)
    sp.setRenderHint(QPainter.Antialiasing, True)
    f = QFont("Microsoft YaHei")
    f.setPixelSize(15)
    f.setBold(True)
    sp.setFont(f)

    notes = []
    for k, (lid, a, b) in enumerate(cases):
        sa, sb = st.get(a) or {}, st.get(b) or {}
        ax, ay = line_station_xy(sa, lid)
        bx, by = line_station_xy(sb, lid)
        mx, my = (ax + bx) * 0.5, (ay + by) * 0.5
        L = math.hypot(bx - ax, by - ay)
        mv.centerOn(QPointF(mx, my))
        pump(6)
        pm = mv.grab()
        # 场景长度 → 视口像素：直接量两个场景点的视口距离，别猜缩放
        p0 = mv.mapFromScene(QPointF(mx, my))
        p1 = mv.mapFromScene(QPointF(mx + (bx - ax), my + (by - ay)))
        vs = math.hypot(p1.x() - p0.x(), p1.y() - p0.y()) / max(L, 1e-6)
        side = int(max(L * vs * 1.9, 210))
        rect = QRect(int(p0.x() - side // 2), int(p0.y() - side // 2), side, side)
        crop = pm.copy(rect)
        r = k // COLS
        c = k % COLS
        x0 = c * CELL
        y0 = r * (CELL + 22)
        if not crop.isNull():
            sc = crop.scaled(CELL, CELL, Qt.KeepAspectRatio,
                             Qt.SmoothTransformation)
            sp.drawPixmap(x0 + (CELL - sc.width()) // 2,
                          y0 + (CELL - sc.height()) // 2, sc)
        sp.setPen(QPen(QColor("#B4232A")))
        sp.drawRect(x0, y0, CELL - 1, CELL - 1)
        sp.drawText(x0 + 6, y0 + CELL + 16, "%s  %s→%s" % (lid, a, b))
        notes.append("%2d  %-5s %s → %s   段长 %.0f" % (k + 1, lid, a, b, L))
    sp.end()
    out = LOGS / "_trpair_sheet.png"
    sheet.save(str(out))
    (LOGS / "_trpair_sheet.txt").write_text("\n".join(notes), encoding="utf-8")
    print("大图 %s  (%d×%d)" % (out, sheet.width(), sheet.height()))
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
