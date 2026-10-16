# -*- coding: utf-8 -*-
"""把「相邻两站都是换乘站」的那几段线路截出来，肉眼确认"严重变形"长什么样。

用法：
    python tools/_shot_transfer_pair.py
产物写在 logs/ 下：_trpair_<线>_<站A>_<站B>.png
"""
import json
import sys
import tempfile
import shutil
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
from PySide6.QtCore import QPointF                                  # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402

LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)

# 要截的段：<线号>  <站A>  <站B>
CASES = [
    ("1", "会展中心", "岗厦"),
    ("2", "市民中心", "岗厦北"),
    ("2", "岗厦北", "华强北"),
    ("1", "大剧院", "老街"),
    ("2", "湖贝", "黄贝岭"),
    ("4", "福田口岸", "福民"),
    ("9", "红岭南", "红岭"),
    ("11", "红岭南", "华强南"),
]


def pump(n=8):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def set_scale(mv, scale):
    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    pump(8)
    mv._invalidate_nn()
    mv._update_label_visibility()
    pump(10)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(12)
    mv = win.map_view
    dm = CDM.get_data_manager()
    st = dm.all_stations()

    set_scale(mv, 1.0)
    for lid, a, b in CASES:
        sa, sb = st.get(a), st.get(b)
        if not sa or not sb:
            print("跳过（找不到站）：", lid, a, b)
            continue
        cx = (float(sa.get("x", 0)) + float(sb.get("x", 0))) * 0.5
        cy = (float(sa.get("y", 0)) + float(sb.get("y", 0))) * 0.5
        mv.centerOn(QPointF(cx, cy))
        pump(10)
        pm = mv.grab()
        p = LOGS / ("_trpair_%s_%s_%s.png" % (lid, a, b))
        pm.save(str(p))
        # 顺便把"这一段到底用了哪些点"打出来
        print("%-4s %s → %s   截图 %s" % (lid, a, b, p.name))
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
