# -*- coding: utf-8 -*-
"""
tools/_probe_v269_icon.py
========================
把「换乘站专属图标」和「普通站」放在一起放大 10 倍画出来 —— 只为肉眼确认
三段半径（外圈 / 白环带 / 内环 / 核心）没有挤成一坨。真实尺寸 ~10px，
判据见 probe_v269_labels 第 3 节（白环带宽必须 > 0.5px）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os                                    # noqa: E402
import tempfile                              # noqa: E402

import core.data_manager as CDM              # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="v269icon_"))
CDM.STATIONS_FILE = _TMP / "s.json"
CDM.LINES_FILE = _TMP / "l.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import Qt, QPointF, QRectF                    # noqa: E402
from PySide6.QtGui import QPainter, QPixmap, QColor, QFont        # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

from ui.metro_render import (                                     # noqa: E402
    StationDotItem, SCREEN_TRANSFER_R, SCREEN_NORMAL_R,
)
from PySide6.QtWidgets import QStyleOptionGraphicsItem            # noqa: E402

ZOOM = 12.0
LOG = ROOT / "logs"


def main() -> int:
    app = QApplication(sys.argv)
    LOG.mkdir(exist_ok=True)
    pm = QPixmap(480, 300)
    pm.fill(QColor("#F7F9FB"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    for row, zoom in enumerate((12.0, 1.0)):
        # 左：普通站；右：换乘站
        for idx, (is_tr, color) in enumerate([(False, "#00B140"), (True, "#F5A623")]):
            it = StationDotItem("X", {"x": 0, "y": 0, "station_name": "示例",
                                      "is_transfer": is_tr}, color=QColor(color))
            it._view_scale = 1.0 / zoom     # radius() = 屏幕半径 × zoom
            cx = 120.0 + idx * 240.0
            cy = 80.0 + row * 150.0
            p.save()
            p.translate(cx, cy)
            # ★ 不要再额外缩放：`_view_scale = 1/zoom` 已经让 radius() 等于
            #   "屏幕半径 × zoom"（场景单位），1:1 贴到画布上正好就是 zoom 倍。
            opt = QStyleOptionGraphicsItem()
            it.paint(p, opt, None)
            p.restore()
            p.setPen(QColor("#475569"))
            f = QFont("Microsoft YaHei")
            f.setPixelSize(12)
            p.setFont(f)
            p.drawText(QRectF(cx - 70, cy + 45, 140, 20), Qt.AlignCenter,
                       ("普通站 r=%.1f" % SCREEN_NORMAL_R) if not is_tr
                       else ("换乘站 r=%.1f（专属 ◎）" % SCREEN_TRANSFER_R))
    p.setPen(QColor("#94A3B8"))
    f2 = QFont("Microsoft YaHei")
    f2.setPixelSize(13)
    p.setFont(f2)
    p.drawText(QRectF(10, 4, 200, 20), Qt.AlignLeft, "上：放大 12 倍（看设计）")
    p.drawText(QRectF(10, 154, 240, 20), Qt.AlignLeft, "下：**真实尺寸**（1:1 看辨识度）")
    p.end()
    out = LOG / "_v269_icon_design.png"
    print("saved:", out, pm.save(str(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
