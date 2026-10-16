# -*- coding: utf-8 -*-
"""错位数值诊断：把每次收尾的【动画最后一帧】与【真实终帧】对齐，
用相位相关算出两者位移差(dx,dy)。差 >1~2px 就会被肉眼看成"错位/跳一下"。
同时统计收尾时是否重排版（会让站名位置跳变）。
"""
import os
import sys
import time

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, QPointF, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

from core.data_manager import get_data_manager
from ui.map_view import MapView

dm = get_data_manager()
v = MapView()
v.setWindowTitle("MISALIGN")
v.resize(1400, 900)
v.rebuild_lines()
v.reload_stations(dm.all_stations())
v.show()
app.processEvents()
time.sleep(0.6)
v.fit_map()
app.processEvents()
time.sleep(0.5)

records = []


def to_gray(pm):
    from PySide6.QtGui import QImage as _QI
    img = pm.toImage().convertToFormat(_QI.Format.Format_RGB32)
    w, h = img.width(), img.height()
    raw = img.constBits().tobytes()
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w, :3]
    g = arr.astype(np.float32).mean(axis=2)
    # 降采样 1/4 提速
    g = g[::4, ::4]
    g = g - g.mean()
    return g


def phase_shift(a, b):
    """返回把 a 对齐到 b 需要的位移 (dx, dy)"""
    n = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    a = a[:n[0], :n[1]]
    b = b[:n[0], :n[1]]
    A = np.fft.rfft2(a)
    B = np.fft.rfft2(b)
    R = A * np.conj(B)
    R = R / (np.abs(R) + 1e-9)
    r = np.fft.irfft2(R, a.shape)
    idx = np.unravel_index(np.argmax(r), r.shape)
    dy = idx[0] if idx[0] < a.shape[0] // 2 else idx[0] - a.shape[0]
    dx = idx[1] if idx[1] < a.shape[1] // 2 else idx[1] - a.shape[1]
    return dx * 4, dy * 4   # 还原到全分辨率


# 记录收尾前的动画帧 / 收尾后的真实帧
_orig_end = v._end_zoom_snap


def wrapped_end(repaint_now=True):
    before = v._snap_label.pixmap()
    a = to_gray(before) if before and not before.isNull() else None
    r = _orig_end(repaint_now)
    after = v.viewport().grab()
    b = to_gray(after)
    if a is not None and a.shape == b.shape:
        dx, dy = phase_shift(a, b)
        records.append((v._scale, dx, dy))
        print(f"收尾 scale={v._scale:.4f}  动画帧 vs 真实帧 位移 dx={dx:+.0f}px dy={dy:+.0f}px", flush=True)
    return r


v._end_zoom_snap = wrapped_end

# 记录排版的重跑次数与站名方向变化数
_layout_runs = [0]
_side_changes = [0]
_orig_layout = v._update_label_visibility


def wrapped_layout():
    before = {sid: it.label_side() for sid, it in v.station_items.items()}
    _orig_layout()
    changes = sum(1 for sid, it in v.station_items.items() if it.label_side() != before.get(sid))
    _layout_runs[0] += 1
    _side_changes[0] += changes
    print(f"  排版重跑第 {_layout_runs[0]} 次：站名方向变化 {changes} 个", flush=True)


v._update_label_visibility = wrapped_layout
v._zoom_finish.timeout.disconnect()
v._zoom_finish.timeout.connect(v._apply_station_scale_all)

# 手势：每 120ms 一格，共 12 格（中途会触发多次收尾）
from PySide6.QtGui import QWheelEvent as _W


def wheel(delta):
    pos = QPointF(v.viewport().rect().center())
    e = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, delta),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(v.viewport(), e)


_n = [0]


def tick():
    if _n[0] >= 12:
        return
    _n[0] += 1
    wheel(120)


t = QTimer()
t.setInterval(120)
t.timeout.connect(tick)
QTimer.singleShot(500, t.start)
QTimer.singleShot(500 + 12 * 120, t.stop)
QTimer.singleShot(500 + 12 * 120 + 2500, app.quit)
app.exec()

print("\n==== 结论 ====")
if records:
    worst = max(records, key=lambda r: (r[1] ** 2 + r[2] ** 2) ** 0.5)
    print(f"共 {len(records)} 次收尾；最大位移 {worst[1]:+.0f},{worst[2]:+.0f}px (scale={worst[0]:.3f})")
    print('判定：位移 ≤2px 属正常（滚动条取整）；>5px 会明显看到错位/跳一下')
else:
    print("未捕获到收尾对（可能手势期间未触发收尾）")
print(f"排版重跑 {_layout_runs[0]} 次，站名方向累计变化 {_side_changes[0]} 个")
