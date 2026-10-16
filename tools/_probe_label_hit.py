# -*- coding: utf-8 -*-
"""只读诊断：到底哪些站的**站名**点不动（v2.6.36）。

用户原话：「有些文字比如'下沙'一直都不能被拖动（只能跟随站点拖动）」

怀疑：MapView 的"拖站名"分支用的是 `station_at(pos)`（鼠标下最上面那个站点图元），
      而站名矩形常常跟**别的站**的站名/圆点叠在一起 ⇒ 拿到的是 B 站，
      再用 B 的站名矩形去 contains(pos) 就必然 False ⇒ 谁也拖不动。

本脚本把所有站过一遍：站名矩形中心 → station_at 返回谁 → 是否等于自己。
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

_TMP = Path(tempfile.mkdtemp(prefix="hitprobe_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication                    # noqa: E402
from PySide6.QtTest import QTest                              # noqa: E402
from ui.main_window import MainWindow                         # noqa: E402


def pump(n=6):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def set_scale(mv, scale):
    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    mv._update_label_visibility()
    pump(4)


def scan(mv, tag):
    all_items = list(mv.station_items.values())
    bad_self, bad_other, bad_none = [], [], []
    for it in all_items:
        lr = it.label_scene_rect()
        if lr.width() <= 0.5 or lr.height() <= 0.5:
            continue
        c = lr.center()
        hit = mv._label_hit(c) if hasattr(mv, "_label_hit") else mv.station_at(c)
        if hit is None:
            bad_none.append(it)
        elif hit is not it:
            bad_other.append((it, hit))
        elif not it.is_label_visible():
            bad_self.append(it)

    vis = sum(1 for it in all_items if it.is_label_visible())
    print(f"\n===== 缩放 {tag}：主站体 {len(all_items)} 个，站名可见 {vis} 个 =====")
    print(f"① 站名中心**找不到任何站**：{len(bad_none)}")
    for it in bad_none[:12]:
        print(f"     {it.data.get('station_name')}  side={it.label_side()} "
              f"可见={it.is_label_visible()}")
    print(f"② 站名中心命中**别的站**：{len(bad_other)}")
    for it, hit in bad_other[:12]:
        print(f"     {it.data.get('station_name')} ← 命中 "
              f"{hit.data.get('station_name')}")
    print(f"③ 命中自己但站名**当前不可见**：{len(bad_self)}")
    for it in bad_self[:12]:
        print(f"     {it.data.get('station_name')}  side={it.label_side()}")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(10)
    mv = win.map_view

    for sc in (1.0, 0.5, 0.30):
        set_scale(mv, sc)
        scan(mv, sc)

    # 单独看下沙
    for nm in ("下沙", "后海"):
        for it in mv.station_items.values():
            if it.data.get("station_name") == nm:
                lr = it.label_scene_rect()
                c = lr.center()
                hit = mv._label_hit(c)
                print(f"\n[{nm}] side={it.label_side()} 矩形={lr.x():.0f},"
                      f"{lr.y():.0f},{lr.width():.0f}x{lr.height():.0f} "
                      f"可见={it.is_label_visible()} "
                      f"命中={None if hit is None else hit.data.get('station_name')} "
                      f"是自己={hit is it}")
                print(f"   该点所有图元: "
                      f"{[type(g).__name__ for g in mv.scene_.items(c)][:6]}")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
