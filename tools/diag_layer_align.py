# -*- coding: utf-8 -*-
"""图层对齐硬测试：缩放动画进行中，把「合成帧（线路矢量重绘 + 站点 sprite 贴图）」
与「同缩放下的真实渲染帧（站点图元真实绘制）」逐像素比对。
若站点 sprite 位置与线路/真实位置不一致 → 两层错位（肉眼=站点脱离线路）。
"""
import os
import sys
import time

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, QPointF, QRectF, QSizeF, QTimer
from PySide6.QtGui import QPainter, QPixmap, QColor, QWheelEvent, QImage
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

from core.data_manager import get_data_manager
from ui.map_view import MapView

dm = get_data_manager()
v = MapView()
v.setWindowTitle("LAYERALIGN")
v.resize(1400, 900)
v.rebuild_lines()
v.reload_stations(dm.all_stations())
v.show()
app.processEvents()
time.sleep(0.6)
v.fit_map()
app.processEvents()
time.sleep(0.5)

# 目录重组后不要再写死绝对路径：从本脚本位置往上推
_SUBWAY = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(_SUBWAY, "软件", "logs", "zoomseq")
os.makedirs(OUT, exist_ok=True)


def to_arr(pm):
    img = pm.toImage().convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    arr = np.frombuffer(img.constBits().tobytes(), dtype=np.uint8).reshape(h, bpl // 4, 4)
    return arr[:, :w, :3].astype(np.int16)


def wheel(delta):
    pos = QPointF(v.viewport().rect().center())
    e = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, delta),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(v.viewport(), e)


report = []


def compare(tag):
    """在动画进行中比较合成帧 vs 真实帧"""
    if v._zoom_snap is None:
        return
    vp = v.viewport()
    dpr = v.devicePixelRatioF()
    s1 = v._scale
    ax, ay = v._snap_anchor.x(), v._snap_anchor.y()
    asc = v._snap_anchor_scene

    # ① 合成帧（动画正在用的那张）
    comp = v._snap_label.pixmap()
    if comp is None or comp.isNull():
        return
    a_img = comp.toImage().convertToFormat(QImage.Format.Format_RGB32)

    # ② 真实帧：同一缩放/同一锚点，用真实图元渲染（临时显示站点）
    pm = QPixmap(a_img.size())
    pm.setDevicePixelRatio(comp.devicePixelRatio())
    pm.fill(QColor("#F7F9FB"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    d = max(1.0, dpr)
    w_log = vp.width()
    h_log = vp.height()
    top = QPointF(asc.x() - ax / s1, asc.y() - ay / s1)
    src = QRectF(top, QSizeF(w_log / s1, h_log / s1))
    tgt = QRectF(0, 0, w_log, h_log)
    for it in v.station_items.values():
        it.setVisible(True)
    v.scene_.render(p, tgt, src)
    for it in v.station_items.values():
        it.setVisible(False)
    p.end()

    b_img = pm.toImage().convertToFormat(QImage.Format.Format_RGB32)
    if a_img.size() != b_img.size():
        print(f"{tag}: 尺寸不一致 {a_img.size()} vs {b_img.size()}")
        return
    A = to_arr(QPixmap.fromImage(a_img))
    B = to_arr(QPixmap.fromImage(b_img))
    diff = np.abs(A - B).max(axis=2)
    frac = float((diff > 60).mean())
    # 逐行/列投影，找是否存在整体偏移
    rows = (diff > 60).mean(axis=1)
    cols = (diff > 60).mean(axis=0)
    print(f"{tag} scale={s1:.3f}  像素差异>60 的比例 = {frac*100:5.2f}%  "
          f"最大行差异={rows.max():.2f} 最大列差异={cols.max():.2f}", flush=True)
    report.append((s1, frac))
    QPixmap.fromImage(a_img).save(os.path.join(OUT, f"align_{tag}_comp.png"))
    pm.save(os.path.join(OUT, f"align_{tag}_real.png"))


# 手势：滚 3 格后，在动画进行中采样比较
_n = [0]


def tick():
    _n[0] += 1
    if _n[0] <= 3:
        wheel(120)
    elif _n[0] == 4:
        app.processEvents()
        compare("mid1")
    elif _n[0] == 6:
        app.processEvents()
        compare("mid2")
    elif _n[0] == 10:
        app.processEvents()
        compare("mid3")


t = QTimer()
t.setInterval(60)
t.timeout.connect(tick)
QTimer.singleShot(400, t.start)
QTimer.singleShot(400 + 16 * 60, t.stop)
QTimer.singleShot(400 + 16 * 60 + 1200, app.quit)
app.exec()

print("\n==== 图层一致性结论 ====")
if report:
    worst = max(report, key=lambda r: r[1])
    print(f"采样 {len(report)} 次；最大差异比例 {worst[1]*100:.2f}% (scale={worst[0]:.3f})")
    print("说明：站点+站名只占画面一小部分，正常情况下差异比例应在个位数百分比；")
    print("      若 >15% 或行/列差异集中在某一侧，说明站点层与线路层确实错位。")
else:
    print("未采样到动画帧")
