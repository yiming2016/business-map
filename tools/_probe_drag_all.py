# -*- coding: utf-8 -*-
"""只读诊断（v2.6.39）：把**每一个**站的站名都真按真拖一次，列出拖不动的。

用户原话：「只要是转弯处的文字均不能被拖动」
→ 与其猜"转弯处"是什么，不如全量跑一遍，看**到底哪些站拖不动**，再看它们有什么共性。
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

_TMP = Path(tempfile.mkdtemp(prefix="dragall_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QPoint, Qt                                # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402
from ui.metro_render import split_label_ring                        # noqa: E402


def pump(n=6):
    for _ in range(n):
        QTest.qWait(10)
        QApplication.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(20)
    mv = win.map_view
    dm = CDM.get_data_manager()

    # 站点 → 转角（该站在自己线路上"前一站→本站→后一站"的夹角，度）
    #   0° = 笔直；45° = 拐弯；90° = 直角大拐
    turn = {}
    _lines = dm.lines_doc.get("lines") or []
    if isinstance(_lines, dict):
        _lines = list(_lines.values())
    for ln in _lines:
        ids = [s if isinstance(s, str) else s.get("station_id")
               for s in (ln.get("stations") or [])]
        for i, sid in enumerate(ids):
            if i == 0 or i == len(ids) - 1:
                continue
            pa, pb, pc = (dm.all_stations().get(ids[i - 1]),
                          dm.all_stations().get(sid),
                          dm.all_stations().get(ids[i + 1]))
            if not (pa and pb and pc):
                continue
            v1 = (float(pb["x"]) - float(pa["x"]), float(pb["y"]) - float(pa["y"]))
            v2 = (float(pc["x"]) - float(pb["x"]), float(pc["y"]) - float(pb["y"]))
            n1 = (v1[0] ** 2 + v1[1] ** 2) ** 0.5
            n2 = (v2[0] ** 2 + v2[1] ** 2) ** 0.5
            if n1 < 1e-6 or n2 < 1e-6:
                continue
            cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
            cos = max(-1.0, min(1.0, cos))
            import math
            ang = math.degrees(math.acos(cos))
            turn[sid] = max(turn.get(sid, 0.0), ang)

    vp = mv.viewport()
    stuck, okd, offscreen = [], [], []
    items = list(mv.station_items.values())
    for n, it in enumerate(items):
        mv._zoom_anim.stop()
        if mv._zoom_snap is not None:
            mv._abort_zoom_snap()
        mv.centerOn(it.pos())
        pump(5)
        lr = it.label_scene_rect()
        p = mv.mapFromScene(lr.center())
        if not (0 <= p.x() < vp.width() and 0 <= p.y() < vp.height()):
            offscreen.append(it)
            continue
        before = (it.label_off().x(), it.label_off().y())
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier,
                         QPoint(int(p.x()), int(p.y())))
        pump(1)
        grabbed = mv._drag_label is not None and mv._drag_label["item"] is it
        QTest.mouseMove(vp, QPoint(int(p.x()) + 50, int(p.y()) - 30))
        pump(1)
        QTest.mouseMove(vp, QPoint(int(p.x()) + 60, int(p.y()) - 36))
        pump(1)
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier,
                           QPoint(int(p.x()) + 60, int(p.y()) - 36))
        pump(3)
        after = (it.label_off().x(), it.label_off().y())
        moved = abs(after[0] - before[0]) + abs(after[1] - before[1])
        rec = (it.data.get("station_name"), it.label_side(),
               round(turn.get(it.station_id, -1)), grabbed, round(moved))
        if moved < 5:
            stuck.append(rec)
        else:
            okd.append(rec)
        # 复位，别影响下一站
        if moved >= 5:
            it.set_label_off(0.0, 0.0)
        if n % 60 == 0:
            print(f"   …已测 {n}/{len(items)}，拖不动 {len(stuck)}", flush=True)

    print(f"\n总共 {len(items)} 站：能拖 {len(okd)}，拖不动 {len(stuck)}，"
          f"站名不在视口 {len(offscreen)}")
    print(f"\n拖不动的站（站名 / 方位 / 该站转角 / 是否抓住 / 位移）：")
    for r in stuck[:40]:
        print(f"   {r[0]:<8} side={r[1]:<8} 转角={r[2]:>5}°  抓住={r[3]}  位移={r[4]}")
    if stuck:
        angs = [r[2] for r in stuck if r[2] >= 0]
        angs_ok = [r[2] for r in okd if r[2] >= 0]
        if angs:
            print(f"\n拖不动的站 平均转角 {sum(angs)/len(angs):.1f}°  "
                  f"最大 {max(angs)}°（样本 {len(angs)}）")
        if angs_ok:
            print(f"能拖的站   平均转角 {sum(angs_ok)/len(angs_ok):.1f}°  "
                  f"（样本 {len(angs_ok)}）")
        big = [r for r in stuck if r[2] >= 40]
        print(f"拖不动且转角 ≥40°（真·转弯处）的：{len(big)} 个")
        print(f"拖不动但**不拐弯**（转角 <10°）的："
              f"{len([r for r in stuck if 0 <= r[2] < 10])} 个")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
