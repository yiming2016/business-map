# -*- coding: utf-8 -*-
"""探针：缩放为什么会作废 sprite？—— 逐个字段对比签名。

sprite 的设计初衷是"屏幕尺寸恒定、与缩放无关"（Google 地图 marker 模型）。
若真如此，缩放收尾后不该有任何 sprite 过期。实测 349/379 过期 →
说明 `_sprite_sig_key()` 里至少有一个字段其实**随缩放漂移**。
把每个字段缩放前后的值打出来，一眼定位。

运行：python tools/_probe_sig_drift.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def pump(ms):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.0005)


def snap(mv, items, k=8):
    """取若干个站点当前签名的可读版本。"""
    dpr = mv.devicePixelRatioF()
    out = {}
    for it in items[:k]:
        br = it.boundingRect()
        s = mv._scale
        vs = it._view_scale
        out[it.station_id] = {
            "scale": round(s, 5),
            "_view_scale": round(vs, 5),
            "br.w*view_scale": round(br.width() * vs, 3),
            "br.h*view_scale": round(br.height() * vs, 3),
            "int(w)": int(round(br.width() * vs)),
            "int(h)": int(round(br.height() * vs)),
            "radius": round(it.radius(), 4),
            "text_scale_factor": round(it.text_scale_factor(), 5),
            "screen_font_px": round(it.screen_font_px(), 4),
            "label.font.px": it.label.font().pixelSize(),
            "halo*view_scale": round(it.label.halo_width() * vs, 4),
            "label.pos.x*vs": round(it.label.pos().x() * vs, 3),
            "label.pos.y*vs": round(it.label.pos().y() * vs, 3),
            "side": it.label_side(),
            "label_on": it._label_on,
            "sig": it._sprite_sig_key(dpr),
        }
    return out


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    win.activateWindow()
    pump(500)

    mv = win.map_view
    vp = mv.viewport()
    items = list(mv.station_items.values())
    dpr = mv.devicePixelRatioF()

    before = snap(mv, items)

    for pos in (QPoint(400, 400), QPoint(430, 400), QPoint(460, 430)):
        QApplication.sendEvent(vp, QWheelEvent(
            QPointF(pos), vp.mapToGlobal(pos), QPoint(0, 0), QPoint(0, 120),
            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
        pump(30)
    pump(600)          # 等收尾
    mv._sprite_sweep.stop()

    after = snap(mv, items)
    stale = sum(1 for it in items if it.sprite_stale(dpr))
    print(f"scale {before[items[0].station_id]['scale']} → "
          f"{after[items[0].station_id]['scale']}   签名过期 {stale}/{len(items)}")
    print()

    keys = [k for k in before[items[0].station_id] if k != "sig"]
    # 统计每个字段"在样本里漂了多少个"
    print(f"{'字段':22s} {'漂移样本数':>8s}   示例（前 3 个里的第一个漂移项）")
    print("-" * 78)
    for k in keys:
        drift = 0
        example = ""
        for it in items[:8]:
            sid = it.station_id
            b, a = before[sid][k], after[sid][k]
            if b != a:
                drift += 1
                if not example:
                    example = f"{b} → {a}"
        print(f"{k:22s} {drift:>8d}   {example}")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
