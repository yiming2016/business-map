# -*- coding: utf-8 -*-
"""只读诊断（v2.6.37）：连续滚轮缩小 —— 复现「放大 / 错乱 / 整张图消失」。

用户原话：「鼠标滚轮连续滚动缩小会造成放大然后错乱然后整张图消失的问题」

逐格记录 `_zoom_target` / `_scale` / 视口里还剩多少图元，找出：
  ① 缩小方向上出现 scale **变大**（= 用户看到的"放大"）
  ② scale 跳出 [下限, 上限]
  ③ 视口里图元数掉到 0（= "整张图消失"）
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

_TMP = Path(tempfile.mkdtemp(prefix="wheelprobe_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QPoint, QPointF, Qt                # noqa: E402
from PySide6.QtGui import QWheelEvent                         # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402
from PySide6.QtTest import QTest                              # noqa: E402
from ui.main_window import MainWindow                         # noqa: E402


def pump(n=6):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def wheel(mv, delta, vp_pos=None):
    c = vp_pos or mv.viewport().rect().center()
    ev = QWheelEvent(QPointF(c), QPointF(c), QPoint(0, 0), QPoint(0, delta),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    mv.wheelEvent(ev)


def vis_items(mv):
    """当前视口（场景矩形）里有多少个图元 —— 0 = 画面空了。"""
    r = mv.mapToScene(mv.viewport().rect()).boundingRect()
    return len(mv.scene_.items(r))


def run(mv, n, delta, gap_ms, tag):
    print(f"\n===== {tag}：{n} 格 × delta={delta}，间隔 {gap_ms}ms =====")
    print(f"{'格':>4}{'_scale':>10}{'_target':>10}{'视口图元':>10}{'虚拟?':>8}")
    prev = mv._scale
    ups, oob, empty = [], [], []
    lo = mv._min_scale_for_viewport()
    hi = mv._zoom_max
    for i in range(n):
        wheel(mv, delta)
        if gap_ms:
            QTest.qWait(gap_ms)
        QApplication.processEvents()
        s = mv._scale
        if delta < 0 and s > prev + 1e-6:
            ups.append((i, prev, s))
        if s < lo - 1e-6 or s > hi + 1e-6:
            oob.append((i, s))
        nv = vis_items(mv)
        if nv == 0:
            empty.append(i)
        if i % 4 == 0 or ups or oob or nv == 0:
            print(f"{i:>4}{s:>10.4f}{mv._zoom_target:>10.4f}{nv:>10}"
                  f"{'是' if mv._zoom_snap is not None else '否':>8}")
        prev = s
    # 停手，等收尾落盘
    pump(30)
    QTest.qWait(400)
    pump(10)
    print(f"  收尾后 _scale={mv._scale:.4f}  下限={lo:.4f}  上限={hi:.4f}  "
          f"视口图元={vis_items(mv)}")
    print(f"  ① 缩小方向却变大：{len(ups)} 次 {ups[:3]}")
    print(f"  ② 跳出上下限：{len(oob)} 次 {oob[:3]}")
    print(f"  ③ 视口图元为 0：{len(empty)} 次 {empty[:3]}")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(20)
    mv = win.map_view
    print(f"起始 _scale={mv._scale:.4f}  下限={mv._min_scale_for_viewport():.4f}")

    run(mv, 20, -120, 40, "正常速度连滚缩小")
    run(mv, 60, -120, 0, "极快连滚缩小（不给动画时间）")
    run(mv, 30, 120, 20, "再连续放大回去")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
