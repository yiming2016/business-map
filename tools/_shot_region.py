# -*- coding: utf-8 -*-
"""只读：用**真实的 MapView**（含站名防重叠排版）把某块区域离屏渲染成 PNG。
这是"软件里到底长什么样"的确定性证据，不受窗口大小/位置影响。

用法:
    python tools/_shot_region.py <cx> <cy> <half> [scale] [outscale] [outname]
"""
import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                       # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="vshot_"))
_REAL = CDM.DATA_DIR
for _n in ("stations.json", "lines.json"):
    if (_REAL / _n).exists():
        shutil.copy(_REAL / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QRectF                     # noqa: E402
from PySide6.QtGui import QFont, QImage, QPainter, QColor   # noqa: E402
from PySide6.QtWidgets import QApplication            # noqa: E402

from ui.main_window import MainWindow                 # noqa: E402


def pump(n=14):
    for _ in range(n):
        QApplication.processEvents()


def main():
    cx, cy, half = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    scale = float(sys.argv[4]) if len(sys.argv) > 4 else 0.40
    outscale = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
    name = sys.argv[6] if len(sys.argv) > 6 else "_region.png"

    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(40)
    mv = win.map_view

    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9), mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    mv._apply_line_width()
    pump(8)
    mv._invalidate_nn()
    mv._update_label_visibility()
    pump(10)

    W = int(half * 2 * scale * outscale)
    H = W
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    mv.scene_.render(p, QRectF(0, 0, W, H),
                     QRectF(cx - half, cy - half, half * 2, half * 2))
    p.end()
    out = ROOT / "logs" / name
    img.save(str(out))
    print("saved", out, img.size())
    win.close()


main()
