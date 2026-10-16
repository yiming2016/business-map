# -*- coding: utf-8 -*-
"""
只读诊断（v2.6.54）：复现「站名拖到合适位置，换个倍率就错位」。

用户原话：「最大的问题是文字每次调整到合适位置，缩放到其他倍率下后就可能错位」。

做法：在 1.0 档把几个站的站名**真拖一下**（走 MapView 自己的鼠标事件），
      然后跨 9 个倍率档各量一次：
        A 存下来的偏移 `label_off()`（**场景单位**，理论上恒定不变）
        B 实际渲染：站名框中心 − 圆点中心（场景单位）
        C 站名可见性、屏幕字号
      ⇒ 谁在变，病根就在谁身上：
        - A 变了 ⇒ 有代码在缩放时**改写了用户设的偏移**（最严重）；
        - A 没变、B 变了 ⇒ 排版器/避让/字号取整在换档时把字挪了；
        - A、B 都没变但看着"错位" ⇒ 是可见性或圆点大小变了造成的错觉。
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

_TMP = Path(tempfile.mkdtemp(prefix="labzoom_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QPoint, QPointF, Qt                      # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402

STEPS = (0.115, 0.15, 0.25, 0.4, 0.7, 1.0, 2.0, 4.0, 8.0)


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


def drag(mv, a: QPoint, b: QPoint):
    QTest.mousePress(mv.viewport(), Qt.LeftButton, Qt.NoModifier, a, 10)
    pump(2)
    QTest.mouseMove(mv.viewport(), b, 10)
    pump(2)
    QTest.mouseMove(mv.viewport(), QPoint(b.x() + 2, b.y() + 2), 10)
    pump(2)
    QTest.mouseRelease(mv.viewport(), Qt.LeftButton, Qt.NoModifier, b, 10)
    pump(6)


def rendered_off(it):
    r = it.label_scene_rect()
    if r.isNull() or r.width() <= 0:
        return None
    return (r.center().x() - it.pos().x(), r.center().y() - it.pos().y())


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(10)
    mv = win.map_view
    set_scale(mv, 1.0)

    # 挑 3 个站：一个普通站、一个换乘站、一个站名容易被挤的
    picks = []
    for sid, it in mv.station_items.items():
        if len(picks) >= 3:
            break
        if bool(it.data.get("is_transfer")) and len(picks) == 1:
            picks.append((sid, it))
        elif not bool(it.data.get("is_transfer")) and len(picks) in (0, 2):
            picks.append((sid, it))
    if len(picks) < 2:
        for sid, it in list(mv.station_items.items())[:3]:
            picks.append((sid, it))

    for sid, it in picks:
        # 在 1.0 档把站名**真的拖一下**（起点落在站名矩形中心，才走得到 _label_hit）
        mv.centerOn(it)
        pump(6)
        lr = it.label_scene_rect()
        if lr.isNull() or lr.width() <= 0:
            sp = mv.mapFromScene(it.pos())
            sp = QPoint(sp.x() + 14, sp.y() + 14)
        else:
            c = mv.mapFromScene(lr.center())
            sp = QPoint(int(c.x()), int(c.y()))
        drag(mv, sp, QPoint(sp.x() - 26, sp.y() - 34))
        print(f"\n===== {sid}（{'换乘' if it.data.get('is_transfer') else '普通'}）=====")
        print("  档位    存偏移(场景)   实际渲染(场景)    字框宽(场景)  字号px  方位/圈  可见")
        axs, ays, bxs, bys, ws = [], [], [], [], []
        for s in STEPS:
            set_scale(mv, s)
            o = it.label_off()
            r = rendered_off(it)
            w = it.label.boundingRect().width() * it.label_scale()
            axs.append(o.x()); ays.append(o.y()); ws.append(w)
            if r:
                bxs.append(r[0]); bys.append(r[1])
            print(f"  {s:>5.3f}  ({o.x():7.2f},{o.y():7.2f})  "
                  f"{('(%7.2f,%7.2f)' % r) if r else '  （站名隐藏）':>18}   "
                  f"{w:8.2f}   {it.label.font().pixelSize():4d}   "
                  f"{it.label_side():>8}   {'是' if r else '否'}")
        def rng(v):
            return (max(v) - min(v)) if len(v) > 1 else 0.0
        print(f"  ⇒ 存的偏移跨档极差：x {rng(axs):.2f} / y {rng(ays):.2f} 场景单位"
              f"（**这一项必须是 0**）")
        if bxs:
            print(f"  ⇒ 实际渲染跨档极差：x {rng(bxs):.2f} / y {rng(bys):.2f} 场景单位"
                  f"（测到 {len(bxs)}/{len(STEPS)} 档）")
        print(f"  ⇒ 字框**场景**宽度跨档极差：{rng(ws):.2f}（**这一项也必须是 0**）")

    print("\n[DONE] 只读，未改任何文件")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
