# -*- coding: utf-8 -*-
"""
_shot_station_copy.py —— 给「站点文案落地」出视觉验收图（右侧信息面板里能看到文案）。

用法：python tools/_shot_station_copy.py [--station 华强北] [--more 福田,机场东]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

import core.data_manager as DM
from ui.main_window import MainWindow


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--station", default="华强北")
    ap.add_argument("--more", default="")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    app.processEvents()

    tmp = Path(tempfile.mkdtemp(prefix="shot_copy_"))
    DM.STATIONS_FILE = tmp / "stations.json"      # ★ 测试脚本不许写真数据
    DM.LINES_FILE = tmp / "lines.json"

    out_dir = ROOT / "logs"
    out_dir.mkdir(exist_ok=True)

    ids = [args.station] + [s for s in args.more.split(",") if s.strip()]
    for sid in ids:
        st = win.dm.all_stations().get(sid)
        if st is None:
            print("[SKIP] 数据里没有 %s" % sid)
            continue
        win.map_view.select_station(sid)
        win.map_view.zoom_to_station(sid)
        win.info_panel.show_station(sid)
        app.processEvents()
        app.processEvents()
        path = out_dir / ("_文案落地_%s.png" % sid)
        if not win.grab().save(str(path)):
            print("[FAIL] 保存失败 %s" % path)
            return 1
        print("[OK] %-8s %s   简介 %d 字 / 地标 %d 字 / 备注 %d 字 / 设施 %d 字"
              % (sid, path.name, len(st.get("description") or ""),
                 len(st.get("landmarks") or ""), len(st.get("notes") or ""),
                 len(st.get("facilities") or "")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
