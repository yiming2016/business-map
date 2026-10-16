# -*- coding: utf-8 -*-
"""
tools/_shot_v2612.py
====================
v2.6.12 的**肉眼验收图**（只出图，判据在回归脚本里）：

  ① 换乘站图标 vs 普通站并排放大 —— 看「更大更醒目」做到没做到
  ② 鼠标悬浮某条线路的效果 —— 那条线加粗、其余变淡（与左侧图例悬停一致）

★ 只读真数据、不写（`MainWindow.close()` 里有 `dm.save()` ⇒ 数据指到临时副本）。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="v2612shot_"))
for _n in ("stations.json", "lines.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import Qt, QPointF                       # noqa: E402
from PySide6.QtGui import QPainter, QPixmap, QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402
from PySide6.QtWidgets import QStyleOptionGraphicsItem       # noqa: E402

import ui.metro_render as MR                                 # noqa: E402
from ui.main_window import MainWindow                        # noqa: E402

_LOGS = ROOT / "logs"
_LOGS.mkdir(exist_ok=True)
_KEEP: list = []


def _pump(n: int = 14) -> None:
    for _ in range(n):
        QApplication.processEvents()


def shot_icons() -> Path:
    """普通站 / 换乘站并排放大（每格按换乘站直径留足空间）。"""
    zoom = 12.0
    cell = int(MR.SCREEN_TRANSFER_R * zoom * 2 + 40)
    pm = QPixmap(cell * 2, cell)
    pm.fill(QColor("#F7F9FB"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    for i, tr in enumerate((False, True)):
        it = MR.StationDotItem("T%d" % i,
                               {"x": 0, "y": 0, "station_name": "测",
                                "is_transfer": tr},
                               color=QColor("#1565C0"))
        it._view_scale = 1.0 / zoom
        p.save()
        p.translate(cell * (i + 0.5), cell / 2.0)
        it.paint(p, QStyleOptionGraphicsItem(), None)
        p.restore()
    p.end()
    out = _LOGS / "_v2612_icons.png"
    pm.save(str(out))
    return out


def shot_hover() -> Path:
    """地图里悬浮 1 号线（黄线方向）的效果：那条加粗、其余变淡。"""
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    _KEEP.append(win)
    _pump(40)
    mv = win.map_view
    mv._apply_zoom_transform(1.0 / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    mv._apply_line_width()
    _pump(20)

    # 挑一条线路，把视口挪到它身上
    lid = sorted(mv.line_items.keys())[0]
    it = mv.line_items[lid]
    n = it.path().elementCount()
    e = it.path().elementAt(n // 2)
    mv.centerOn(QPointF(e.x, e.y))
    _pump(24)

    before = mv.map_view_grab() if hasattr(mv, "map_view_grab") else mv.grab()
    mv.highlight_line(lid)          # = 鼠标悬浮在这条线上时的效果
    _pump(24)
    after = mv.grab()
    out = _LOGS / "_v2612_hover.png"
    after.save(str(out))
    print("      悬浮线路 = %s（其余 %d 条 opacity 0.18）"
          % (lid, len(mv.line_items) - 1))
    del before
    mv.highlight_line("")
    return out


def main() -> int:
    app = QApplication(sys.argv)
    a = shot_icons()
    b = shot_hover()
    for p in (a, b):
        im = QImage(str(p))
        print("[OK] %s  %dx%d" % (p, im.width(), im.height()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
