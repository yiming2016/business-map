# -*- coding: utf-8 -*-
"""只读诊断（v2.6.43 追查）：**在低倍率拖过的站名**，切到高倍率会不会错位。

用户原话：「不同倍率下调整文字后所在的位置有所不同，比如在低倍率下设定了位置，
          高倍率下文字会错位，没有在其他倍率下记忆移动的情况」

量法：在 0.15 档把某站名真拖一段 ⇒ 跨档量「字框中心 − 站点中心」这个**场景向量**。
      等比/记住 = 各档这个向量完全一致；只要 side 被重挑、或偏移被换算过，就会飘。
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

_TMP = Path(tempfile.mkdtemp(prefix="offxz_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QPoint, QPointF, Qt                       # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402


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


def drag(mv, it, dx=70, dy=-40):
    mv._zoom_anim.stop()
    if mv._zoom_snap is not None:
        mv._abort_zoom_snap()
    mv.centerOn(QPointF(it.pos().x(), it.pos().y()))
    pump(6)
    box = it.label_scene_rect()
    p = mv.mapFromScene(box.center())
    vp = mv.viewport()
    if not (0 <= p.x() < vp.width() and 0 <= p.y() < vp.height()):
        return False
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(p.x()), int(p.y())))
    pump(2)
    QTest.mouseMove(vp, QPoint(int(p.x()) + dx, int(p.y()) + dy))
    pump(2)
    QTest.mouseMove(vp, QPoint(int(p.x()) + dx + 10, int(p.y()) + dy + 6))
    pump(2)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier,
                       QPoint(int(p.x()) + dx + 10, int(p.y()) + dy + 6))
    pump(6)
    return True


def vec(mv, it):
    """字框中心 − 站点中心（场景单位）。"""
    r = it.label_scene_rect()
    return (r.center().x() - it.pos().x(), r.center().y() - it.pos().y())


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(20)
    mv = win.map_view

    tgt = None
    for it in mv.station_items.values():
        if it.data.get("station_name") == "下沙":
            tgt = it
            break
    tgt = tgt or list(mv.station_items.values())[0]
    name = tgt.data.get("station_name")
    print(f"测试站：{name}")

    # ---------- ① 拖之前：各档基准位置 ----------
    print("\n--- 拖之前（各档自动摆位）---")
    print(f"{'缩放':>6}{'方位':>8}{'向量(场景)':>26}{'可见':>6}")
    for sc in (1.00, 1.50, 2.00, 3.00, 4.00, 6.00, 8.00):
        set_scale(mv, sc)
        v = vec(mv, tgt)
        print(f"{sc:>6.2f}{tgt.label_side():>8}"
              f"{'(' + format(v[0], '.1f') + ',' + format(v[1], '.1f') + ')':>26}"
              f"{('是' if tgt.is_label_visible() else '★否'):>6}")

    # ---------- ② 在 0.15 档拖一段 ----------
    set_scale(mv, 1.00)
    ok_drag = drag(mv, tgt)
    print(f"\n在 1.00 档拖动：{'成功' if ok_drag else '★失败'}，"
          f"label_off = ({tgt.label_off().x():.1f}, {tgt.label_off().y():.1f})")

    print("\n--- 拖之后（跨档看是否记住）---")
    print(f"{'缩放':>6}{'方位':>8}{'向量(场景)':>26}{'可见':>6}")
    vs = []
    for sc in (1.00, 1.50, 2.00, 3.00, 4.00, 6.00, 8.00):
        set_scale(mv, sc)
        v = vec(mv, tgt)
        vs.append(v)
        print(f"{sc:>6.2f}{tgt.label_side():>8}"
              f"{'(' + format(v[0], '.1f') + ',' + format(v[1], '.1f') + ')':>26}"
              f"{('是' if tgt.is_label_visible() else '★否'):>6}")

    xs = [v[0] for v in vs]
    ys = [v[1] for v in vs]
    print(f"\n结论：x 极差 {max(xs) - min(xs):.1f} 场景单位，"
          f"y 极差 {max(ys) - min(ys):.1f} 场景单位")
    print("（0 = 各档完全一致；>5 就是用户看到的「错位」）")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
