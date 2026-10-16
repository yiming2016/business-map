# -*- coding: utf-8 -*-
"""
_shot_isolation.py —— 给「双击图例只看这一条线 + 右下角车厢编组卡片」出视觉验收图。

出三张（落到 源码/logs/）：
    _iso_11.png  11 号线：八节，**只画一个列车图标**，7/8 节商务车厢（金色）
    _iso_3.png   3 号线：六节，1/6 弱冷、2-5 强冷
    _iso_10.png  10 号线：八节，1/8 弱冷、2-7 强冷
另出每条的**卡片特写**（2× 放大，方便看清"融入背景"的效果）：
    _iso_<线>_card.png

用法：python tools/_shot_isolation.py [--line 11]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

import core.data_manager as DM
from ui.main_window import MainWindow


def save_card_closeup(win, card, path: Path) -> bool:
    """把卡片区域从真实窗口画面里裁出来放大 2 倍。

    ★ 用 `card.mapTo(win, QPoint(0,0))` 拿**精确**位置，别凭缩略图目测坐标 ——
      目测会裁偏，看着像"卡片跑位了"，其实只是裁歪了。
    """
    img = win.grab().toImage()
    dpr = float(win.devicePixelRatioF()) or 1.0
    tl = card.mapTo(win, QPoint(0, 0))
    pad = 12
    x = max(0, int((tl.x() - pad) * dpr))
    y = max(0, int((tl.y() - pad) * dpr))
    w = min(img.width() - x, int((card.width() + pad * 2) * dpr))
    h = min(img.height() - y, int((card.height() + pad * 2) * dpr))
    if w <= 0 or h <= 0:
        return False
    crop = img.copy(QRect(x, y, w, h))
    out = QImage(w * 2, h * 2, QImage.Format_RGB32)
    out.fill(Qt.white)
    p = QPainter(out)
    p.drawImage(QRect(0, 0, w * 2, h * 2), crop, QRect(0, 0, w, h))
    p.end()
    return bool(out.save(str(path)))          # ★ save() 失败只返回 False，不抛异常


def dblclick_row(row) -> None:
    ev = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(6, 6),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    row.mouseDoubleClickEvent(ev)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--line", default="")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    app.processEvents()

    tmp = Path(tempfile.mkdtemp(prefix="shot_iso_"))
    DM.STATIONS_FILE = tmp / "stations.json"
    DM.LINES_FILE = tmp / "lines.json"

    out_dir = ROOT / "logs"
    out_dir.mkdir(exist_ok=True)

    targets = [args.line] if args.line else ["11", "3", "10"]
    for lid in targets:
        row = next((r for r in win.legend_panel._rows if r.line_id == lid), None)
        if row is None:
            print("[SKIP] 图例里没有 %s" % lid)
            continue
        dblclick_row(row)
        app.processEvents()
        app.processEvents()
        tag = lid.replace("支", "z").replace("线", "")
        path = out_dir / ("_iso_%s.png" % tag)
        pm = win.grab()
        if not pm.save(str(path)):            # ★ 必须查返回值，失败只返回 False
            print("[FAIL] 保存失败 %s" % path)
            return 1
        vis = sum(1 for it in win.map_view.station_items.values() if it.isVisible())
        card = win.consist_card
        closeup = out_dir / ("_iso_%s_card.png" % tag)
        ok_close = save_card_closeup(win, card, closeup)
        print("[OK] %-14s %s  %dx%d  可见站点=%d  卡片=%s%s"
              % ("线路 " + lid, path.name, pm.width(), pm.height(), vis,
                 "显示" if card.isVisible() else "隐藏",
                 "  特写=%s" % closeup.name if ok_close else "  [特写保存失败]"))
        # 退出隔离，准备下一张
        dblclick_row(row)
        app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
