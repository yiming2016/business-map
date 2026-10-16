# -*- coding: utf-8 -*-
"""
tools/_shot_v2611.py
====================
v2.6.11 的**肉眼验收图**（只出图、不下结论，判据在回归脚本里）：

  ① 换乘站新图标（🔄 旋转箭头环）与普通站并排放大 —— 看形状是不是"两段带箭头的弧"
  ② 编辑弹窗「首末班车」表格 —— 看「工作日」下拉与「线路」表头挨不挨紧、
     色块条有没有挂在**下拉正下方**（而不是原来的圆点列）

★ 只读真数据、不写（`MainWindow.close()` 里有 `dm.save()` ⇒ 数据指到临时副本）。
"""
from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                       # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="v2611shot_"))
for _n in ("stations.json", "lines.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import Qt, QPointF                      # noqa: E402
from PySide6.QtGui import (QFont, QPainter, QPixmap, QColor,  # noqa: E402
                           QImage)
from PySide6.QtWidgets import (QApplication,                # noqa: E402
                               QStyleOptionGraphicsItem, QWidget, QVBoxLayout)

import ui.metro_render as MR                                # noqa: E402
from ui.timetable_editor import TimetableEditor             # noqa: E402

_LOGS = ROOT / "logs"
_LOGS.mkdir(exist_ok=True)
_KEEP: list = []          # ★ 别让宿主控件被 GC（否则子控件 C++ 对象一起没）


def _pump(n: int = 12) -> None:
    for _ in range(n):
        QApplication.processEvents()


def shot_icons() -> Path:
    """普通站 / 换乘站并排放大（每格 160px）。"""
    zoom = 14.0
    cell = int(MR.SCREEN_TRANSFER_R * zoom * 2 + 30)
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
    out = _LOGS / "_v2611_icons.png"
    # ★ 放大 3 倍存盘，方便肉眼看（原图每格才 ~176px，弧宽 1.5px 太小）
    pm.scaled(cell * 2 * 3, cell * 3, Qt.KeepAspectRatio,
              Qt.FastTransformation).save(str(out))
    return out


def shot_timetable() -> Path:
    """编辑弹窗里的「首末班车」表格（含日期下拉 + 表头 + 色块条）。"""
    # ★ 必须写成**官方存储格式**（`工作日 · N号线：往X 首HH:MM 末HH:MM；…`），
    #   不然整行解析不了 → 走 `_leftovers` 兜底、原样显示成一坨灰字
    #   （第一版就是这么写的，图里根本没有表格）。
    ed = TimetableEditor(
        "工作日 · 1号线：往罗湖 首06:02 末23:47；往机场东 首06:41 末23:21\n"
        "工作日 · 5号线：往黄贝岭 首06:05 末23:30；往赤湾 首06:10 末23:25\n"
        "工作日 · 11号线：往碧头 首06:20 末23:40；往岗厦北 首06:25 末23:35\n"
        "休息日 · 1号线：往罗湖 首06:20 末23:50；往机场东 首06:45 末23:25")
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(10, 10, 10, 10)
    lay.addWidget(ed)
    host.resize(560, 300)
    host.show()
    _KEEP.append(host)
    _pump(20)
    pm = host.grab()
    out = _LOGS / "_v2611_timetable.png"
    pm.save(str(out))
    return out


def main() -> int:
    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    app.setFont(f)
    a = shot_icons()
    b = shot_timetable()
    for p in (a, b):
        im = QImage(str(p))
        print("[OK] %s  %dx%d" % (p, im.width(), im.height()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
