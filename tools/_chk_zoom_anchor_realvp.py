# -*- coding: utf-8 -*-
"""_chk_zoom_anchor_realvp.py —— 锚点在**真实视口(874×829)**下的权威判定。

为什么要单独做这个：`tools/verify_zoom_anchor.py`、`tools/verify_anchor.py`
都是**独立** `MapView().resize(1400, 900)` —— 而真实 App 里地图两侧有面板，
视口只有 **874×829**（主窗口 1480×900），长宽比从 1.57 变 1.05、
fit 是宽度受限还是高度受限都翻转。锚点漂移与"鼠标在视口的**相对**位置"强相关，
所以尺寸一换结论就可能不成立（这条踩过坑，见技能 pyside6-zoom-anchor-diag）。

外部像素验证（tools/verify_anchor_exe.py）在真机上量出过 121.7px 的"位移"。
它靠"模板匹配"跟踪光标附近 64px 的图像块，而本程序的站名会**随缩放变大**
（v2.5.4 起 10→20px）且防重叠排版会随缩放增删站名 —— 于是"缩放前后"的局部画面
**不是纯放大**，模板匹配会失准。所以需要一个**不依赖像素**的判据：
直接问 `mapToScene(光标)` —— 锚点正确 ⇔ 光标下的场景点在缩放前后不变。

判据：|p1 - p0| * 缩放 < 2 屏幕px（理想 0；>2px 肉眼可见）。
覆盖：放大 / 缩小、视口 5 个相对位置、以及"连滚多格"和"滚一下换位置再滚"。

运行：
    python tools/_chk_zoom_anchor_realvp.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

PASS = FAIL = 0
TOL_PX = 2.0
POSITIONS = [0.06, 0.28, 0.50, 0.72, 0.94]      # 视口宽度方向的相对位置


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK]   %s   %s" % (name, detail))
    else:
        FAIL += 1
        print("  [FAIL] %s   %s" % (name, detail))


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    app.processEvents()
    mv = win.map_view
    win.dm.save = lambda *a, **k: None
    vp = mv.viewport()

    def pump(ms: int) -> None:
        """真正驱动事件循环（time.sleep 会饿死 QTimer，动画根本不跑）。"""
        t_end = time.time() + ms / 1000.0
        while time.time() < t_end:
            app.processEvents()
            time.sleep(0.005)

    def wheel(delta: int, pos: QPoint) -> None:
        p = QPointF(pos)
        e = QWheelEvent(p, p, QPoint(0, 0), QPoint(0, delta), Qt.NoButton,
                        Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(vp, e)

    def settle() -> None:
        pump(1400)

    def drift_px(pos: QPoint, notches: int, up: bool) -> tuple:
        p0 = mv.mapToScene(pos)
        s0 = mv.transform().m11()
        for _ in range(notches):
            wheel(120 if up else -120, pos)
            pump(70)
        settle()
        p1 = mv.mapToScene(pos)
        s1 = mv.transform().m11()
        d = ((p1.x() - p0.x()) ** 2 + (p1.y() - p0.y()) ** 2) ** 0.5
        return d * s1, s0, s1

    print("=" * 78)
    print("视口 %dx%d  （真实 App 的地图视口）  站点 %d  线路 %d"
          % (vp.width(), vp.height(), len(mv.station_items), len(mv.line_items)))
    print("判据：光标下的场景点在缩放前后漂移 < %.0f 屏幕px" % TOL_PX)

    # ---------- 放大：视口 5 个相对位置 ----------
    print("\nA 鼠标停在原地滚轮【放大】4 格")
    ys = int(vp.height() * 0.80)
    for f in POSITIONS:
        pos = QPoint(int(vp.width() * f), ys)
        d, s0, s1 = drift_px(pos, 4, up=True)
        ok("放大 x=%.2f*w (%.1f倍→%.1f倍) 漂移 <%.0fpx" % (f, s0, s1, TOL_PX),
           d < TOL_PX, "实测 %.2fpx" % d)

    # ---------- 缩小 ----------
    print("\nB 鼠标停在原地滚轮【缩小】4 格")
    for f in (0.10, 0.50, 0.90):
        pos = QPoint(int(vp.width() * f), int(vp.height() * 0.30))
        d, s0, s1 = drift_px(pos, 4, up=False)
        ok("缩小 x=%.2f*w (%.3f倍→%.3f倍) 漂移 <%.0fpx" % (f, s0, s1, TOL_PX),
           d < TOL_PX, "实测 %.2fpx" % d)

    # ---------- 连滚多格 ----------
    print("\nC 鼠标停在原地连滚 10 格（用户快速滚动）")
    pos = QPoint(int(vp.width() * 0.85), int(vp.height() * 0.85))
    d, s0, s1 = drift_px(pos, 10, up=True)
    ok("连滚 10 格漂移 <%.0fpx" % TOL_PX, d < TOL_PX,
       "%.2f倍→%.2f倍  实测 %.2fpx" % (s0, s1, d))

    # ---------- 滚一下换位置再滚（真机最常见的动作） ----------
    print("\nD 在 A 滚 1 格 → 立刻挪到 B 再滚 3 格（锚点应改到 B）")
    A = QPoint(int(vp.width() * 0.20), int(vp.height() * 0.70))
    B = QPoint(int(vp.width() * 0.80), int(vp.height() * 0.30))

    def displayed_scene_under(pt: QPoint) -> QPointF:
        """【屏幕上显示的】画面里，pt 处对应哪个场景点。

        ★ 动画期间屏幕上放的是**合成快照帧**，不是真实场景 ——
          此时 mapToScene() 量到的不是用户看到的东西。
          合成帧的关系：screen = anchor + (scene - anchor_scene) * _scale
          ⇒ scene = anchor_scene + (pt - anchor) / _scale
          （与 tools/diag_mouse_anchor.py 的 displayed_scene_under 同一套公式）
        """
        if mv._zoom_snap is None:
            return mv.mapToScene(pt)
        s1 = max(mv._scale, 1e-6)
        a, asc = mv._snap_anchor, mv._snap_anchor_scene
        return QPointF(asc.x() + (pt.x() - a.x()) / s1,
                       asc.y() + (pt.y() - a.y()) / s1)

    def drift(pt: QPoint, base: QPointF) -> float:
        s1 = max(mv._scale, 1e-6)
        now = displayed_scene_under(pt)
        return (((now.x() - base.x()) ** 2 + (now.y() - base.y()) ** 2) ** 0.5) * s1

    # ★★ 基线必须取在"挪到 B 的那一刻"（= A 滚完之后），
    #    取在 A 滚之前就错了：绕 A 放大本来就会把 B 处的内容往外推，
    #    那是**设计如此**，不是漂移。实测那一份"错基线"会读出 132px 的假故障。
    wheel(120, A); pump(30)
    base_B = displayed_scene_under(B)
    wheel(120, B); pump(30)
    d1 = drift(B, base_B)
    ok("挪到 B 后第一格：B 下内容不跑（<%.0fpx）" % TOL_PX, d1 < TOL_PX,
       "实测 %.2fpx" % d1)
    dmax = d1
    for _ in range(2):
        wheel(120, B); pump(40)
        dmax = max(dmax, drift(B, base_B))
    ok("继续在 B 滚 2 格：B 下内容累计漂移 <%.0fpx" % TOL_PX, dmax < TOL_PX,
       "实测 %.2fpx" % dmax)

    # 收尾之后（真实变换落地）也必须回到同一个地方 —— 否则就是"松手弹一下"
    settle()
    pB1 = mv.mapToScene(B)
    s1 = max(mv._scale, 1e-6)
    d_end = (((pB1.x() - base_B.x()) ** 2 + (pB1.y() - base_B.y()) ** 2) ** 0.5) * s1
    ok("收尾后 B 下内容仍然没跑（<%.0fpx）" % TOL_PX, d_end < TOL_PX,
       "实测 %.2fpx（合成帧 → 真实帧 不跳）" % d_end)

    print("\n" + "=" * 78)
    print("通过 %d 项，失败 %d 项" % (PASS, FAIL))
    if FAIL == 0:
        print("全部通过 ✅  —— 锚点不依赖像素匹配，这就是权威判据")
    print("=" * 78)
    win.hide()


if __name__ == "__main__":
    main()
