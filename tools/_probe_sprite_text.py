# -*- coding: utf-8 -*-
"""只读探针：比对「合成帧里站名的落点」与「真实帧里站名的落点」。

用来定位 v2.6.31 把 sprite 改成"只烤文字"之后，小档整幅差异从 4% 涨到 7% 的原因。
"""
from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="spriteprobe_"))
for _n in ("stations.json", "lines.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QPointF, QPoint, Qt                # noqa: E402
from PySide6.QtGui import QFont, QWheelEvent                 # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402
from PySide6.QtTest import QTest                             # noqa: E402

from ui.main_window import MainWindow                        # noqa: E402
from ui.metro_render import LABEL_SPRITE_PAD                 # noqa: E402


def pump(n=6):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def main():
    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(40)
    mv = win.map_view
    s = mv._scale
    print("起始缩放 %.4f" % s)

    worst = []
    for sid, it in mv.station_items.items():
        if not it._label_on:
            continue
        # 真实帧：label 在屏幕上的左上角（相对站点中心）
        lp = it.label.pos()
        sx = mv.mapFromScene(it.pos())
        real_l = mv.mapFromScene(it.label.sceneBoundingRect().topLeft())
        # 合成帧：_compose_frame 里算的落点
        bx = it._label_box(None, s)
        comp_l = (sx.x() + bx.left() * s - LABEL_SPRITE_PAD,
                  sx.y() + bx.top() * s - LABEL_SPRITE_PAD)
        d = (abs(real_l.x() - comp_l[0]), abs(real_l.y() - comp_l[1]))
        worst.append((max(d), sid, d, it._label_side,
                      it.label.boundingRect().width(),
                      it.label.sceneBoundingRect().width()))
    worst.sort(reverse=True)
    print("站名落点偏差（真实 vs 合成帧）：n=%d" % len(worst))
    for w in worst[:8]:
        print("  %-8s side=%-8s 偏差=(%.2f, %.2f)  标签宽 local=%.1f scene=%.1f"
              % (w[1], w[3], w[2][0], w[2][1], w[4], w[5]))
    import statistics
    mx = [w[0] for w in worst]
    print("  最大 %.2f  中位 %.2f  平均 %.2f" % (mx[0], statistics.median(mx),
                                              sum(mx) / len(mx)))


if __name__ == "__main__":
    main()
