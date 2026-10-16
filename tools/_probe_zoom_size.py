# -*- coding: utf-8 -*-
"""只读探针：逐帧记录缩放过程中「虚拟缩放 / 真实变换 / 圆点尺寸 / 字号 / 线宽」。

用来回答用户的问题：「为什么现在会先缩小再放大；先放大再缩小？文字和线路粗细均如此」

判据：动画期间的**合成帧**与收尾后的**真实帧**，同一项必须一致；
      哪一项在收尾那一步**反向跳一下**，就是用户看到的那个现象。
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

_TMP = Path(tempfile.mkdtemp(prefix="zoomprobe_"))
_REAL = CDM.DATA_DIR
for _n in ("stations.json", "lines.json"):
    if (_REAL / _n).exists():
        shutil.copy(_REAL / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QPointF, QPoint, Qt                # noqa: E402
from PySide6.QtGui import QFont                       # noqa: E402
from PySide6.QtWidgets import QApplication           # noqa: E402
from PySide6.QtTest import QTest                         # noqa: E402
from PySide6.QtGui import QWheelEvent                # noqa: E402

from ui.main_window import MainWindow                 # noqa: E402
from ui.metro_render import (                         # noqa: E402
    effective_font_px, line_scene_width)


def pump(n=6):
    """★ 必须**真的等**：QTimer 不靠 processEvents 推进，靠时间。"""
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def set_scale(mv, scale):
    """照 _chk 脚本的写法把真实变换与虚拟缩放对齐。"""
    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    pump(8)
    mv._invalidate_nn()
    mv._update_label_visibility()
    pump(10)


def snap(mv, tag):
    """记录当前这一刻的四项尺寸。"""
    s = mv._scale
    real = mv.transform().m11()
    it = next((v for v in mv.station_items.values() if not v.is_transfer),
                next(iter(mv.station_items.values())))
    lid = next(iter(mv.line_items.keys()))
    lw_scene = mv.line_items[lid].pen().widthF()
    return dict(tag=tag, virt=s, real=real,
                dot=it.screen_radius(), font=effective_font_px(s),
                lw_scene=lw_scene, lw_screen=lw_scene * real,
                sprite=(it._sprite[0].width() if getattr(it, "_sprite", None)
                        else -1),
                snap_on=mv._zoom_snap is not None, ink=frame_ink(mv))


def frame_ink(mv):
    """数合成帧里有多少**彩色像素** —— 线越粗，彩色面积越大（线的总长不变时
       彩色面积 ∝ 线宽）。用来判断"线路粗细在动画期间到底跟不跟缩放"。"""
    lab = getattr(mv, "_snap_label", None)
    if lab is None or not lab.isVisible():
        return -1
    pm = lab.pixmap()
    if pm is None or pm.isNull():
        return -1
    im = pm.toImage()
    w, h = im.width(), im.height()
    n = 0
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            c = im.pixelColor(x, y)
            r, g, b = c.red(), c.green(), c.blue()
            if max(r, g, b) - min(r, g, b) > 60 and max(r, g, b) > 90:
                n += 1
    return n


def wheel(mv, times, up=True):
    c = mv.viewport().rect().center()
    for _ in range(times):
        ev = QWheelEvent(QPointF(c), QPointF(c),
                         QPoint(0, 0), QPoint(0, 120 if up else -120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        mv.wheelEvent(ev)
        pump(1)


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

    for up, name in ((True, "放大"), (False, "缩小")):
        # 先回到中间档
        set_scale(mv, 0.45)
        rows = [snap(mv, "起点")]
        wheel(mv, 6, up)
        for i in range(10):
            pump(1)
            rows.append(snap(mv, "帧%d" % i))
        # 等收尾
        mv._zoom_finish.stop()
        mv._apply_station_scale_all()
        pump(30)
        rows.append(snap(mv, "收尾"))

        print("\n===== %s（6 格滚轮）=====" % name)
        print("%-6s %7s %7s %7s %7s %9s %8s %6s %8s" %
              ("时刻", "虚拟", "真实", "圆点px", "字号", "线宽场景", "线宽屏", "快照", "彩色px"))
        for r in rows:
            print("%-6s %7.4f %7.4f %7.2f %7.2f %9.2f %8.2f %6s %8d" %
                  (r["tag"], r["virt"], r["real"], r["dot"], r["font"],
                   r["lw_scene"], r["lw_screen"], r["snap_on"], r["ink"]))


if __name__ == "__main__":
    main()
