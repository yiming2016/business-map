# -*- coding: utf-8 -*-
"""只读诊断（v2.6.42 追查）：字与线的净空到底跟不跟缩放等比。

用户原话（v2.6.42 已经改过 gap 为场景单位之后）：
    「缩小会远离、放大会靠近这个问题还是没修复」

判法：**只看场景单位**。等比 = "字近边到站点中心的场景距离"在各档恒定；
      若它随缩小变大 ⇒ 有量还是屏幕恒定（病根）。

同时把三个嫌疑量一起打出来定位：
    font_scene = 屏幕字号 / 缩放        （字在地图里多大；恒定 = 等比）
    dot_scene  = 圆点屏幕半径 / 缩放    （圆点物理下限 3.4px 会让它在小档变"大"）
    line_scene = 线宽场景               （物理下限 3.0px 同理）
    clear_scene= 字近边 → 站点中心（场景）
"""
from __future__ import annotations

import sys
import tempfile
import shutil
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="gapzoom_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402
import ui.metro_render as MR                                        # noqa: E402


def pump(n=6):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def set_scale(mv, scale):
    mv._zoom_anim.stop()
    if mv._zoom_snap is not None:
        mv._abort_zoom_snap()
    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    mv._update_label_visibility()
    pump(5)


def ring_of(side: str) -> int:
    b, r = MR.split_label_ring(side)
    return r


def clear_scene(it) -> float:
    """字框近边 → 站点中心，场景单位。"""
    r = it.label_scene_rect()
    cx, cy = it.pos().x(), it.pos().y()
    dx = max(r.left() - cx, cx - r.right(), 0.0)
    dy = max(r.top() - cy, cy - r.bottom(), 0.0)
    return (dx * dx + dy * dy) ** 0.5


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(20)
    mv = win.map_view

    # 挑 ring=0、没手拖过的站当样本
    pool = []
    for it in mv.station_items.values():
        if not it.is_label_visible():
            continue
        if ring_of(it.label_side()) != 0:
            continue
        if it.label_off().x() or it.label_off().y():
            continue
        pool.append(it)
    pool.sort(key=lambda i: i.data.get("station_name") or "")
    sample = pool[:200:17]          # 均匀取十来个
    print(f"样本 {len(sample)} 站（ring=0、无手拖）："
          f"{', '.join(i.data.get('station_name') for i in sample[:8])} ...")

    print(f"\n{'缩放':>6}{'字号场景':>10}{'圆点半宽场景':>14}"
          f"{'线半宽场景':>12}{'净空中位':>10}{'净空/圆点半宽':>14}")
    rows = []
    for sc in (0.10, 0.15, 0.25, 0.40, 0.70, 1.00, 2.00, 3.00, 4.00):
        set_scale(mv, sc)
        vals = []
        for it in sample:
            if ring_of(it.label_side()) != 0:      # 这一档被推到外圈 ⇒ 不算基准
                continue
            vals.append(clear_scene(it))
        med = statistics.median(vals) if vals else float("nan")
        font_scene = MR.effective_font_px(sc) / sc
        dot_scene = MR.normal_dot_screen_r(sc) / sc
        line_scene = MR.line_scene_width(sc) / 2
        rows.append((sc, font_scene, dot_scene, line_scene, med))
        print(f"{sc:>6.2f}{font_scene:>10.1f}{dot_scene:>14.2f}"
              f"{line_scene:>12.2f}{med:>10.2f}"
              f"{med / max(dot_scene, 1e-6):>14.2f}   （n={len(vals)}）")

    print("\n--- 结论 ---")
    cs = [r[4] for r in rows]
    print(f"净空中位：min={min(cs):.2f} max={max(cs):.2f} 极差比={max(cs)/min(cs):.2f}×")
    fs = [r[1] for r in rows]
    print(f"字号场景：min={min(fs):.2f} max={max(fs):.2f} 极差比={max(fs)/min(fs):.2f}×")
    ds = [r[2] for r in rows]
    print(f"圆点半宽场景：min={min(ds):.2f} max={max(ds):.2f} 极差比={max(ds)/min(ds):.2f}×")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
