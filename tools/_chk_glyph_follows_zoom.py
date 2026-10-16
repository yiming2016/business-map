# -*- coding: utf-8 -*-
"""回归：缩放动画的**合成帧**里，圆点/药丸必须按**当前虚拟缩放**现算尺寸。

用户原话：「为什么现在会先缩小再放大；先放大再缩小？文字和线路粗细均如此」

病根（v2.6.30）：合成帧用预渲染 sprite 画站点，而 sprite 每帧只准重建 6 个
⇒ 圆点被冻结在手势起点的尺寸，松手那一步才跳到新尺寸（0.45→1.067 实测
   5.21px → 11.76px）。
根治（v2.6.31）：sprite 只烤**文字**，圆点由 draw_glyph_screen() 矢量实时画。

★ 为什么不用"合成帧 vs 真实帧"的像素比对（_chk_reveal_align）来守：
  圆点面积占屏幕比例太小 —— 实测把圆点强行缩到 30%，整幅差异也只从 1.00%
  涨到 1.50%，照样通过 ⇒ 那个判据**抓不住**这条。
  这里改成盯"合成帧实际用的缩放"，直接、且与像素无关。

判据：
  A 最后一帧合成用的缩放 == 收尾后的真实缩放（<2%）
  B 合成用的缩放**不是常量**（跟随手势连续变；冻住时比值 == 1）
  C 合成帧算出的圆点半径 == 真实帧的半径（<0.5px）
  D 变异自检：把 draw_glyph_screen 换成"用冻结的 _view_scale 画"⇒ A/B 必须炸

运行：
    ...\\python.exe tools/_chk_glyph_follows_zoom.py
"""
from __future__ import annotations

import sys
import types
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="glyphchk_"))
for _n in ("stations.json", "lines.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QPointF, QPoint, Qt                # noqa: E402
from PySide6.QtGui import QFont, QWheelEvent                 # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402
from PySide6.QtTest import QTest                             # noqa: E402

# ★ 2026-10-11：本脚本检的是**现场合成路径**里的圆点（draw_glyph_screen）——
#   该路径只在 ZOOM_BITMAP=0 时生效；位图模式（默认）下缩放帧是位图拉伸，
#   draw_glyph_screen 根本不被调用 ⇒ seen 为空、脚本会崩。这里显式关掉位图模式。
import os as _os                                          # noqa: E402
_os.environ.setdefault("METROEDITOR_ZOOM_BITMAP", "0")

from ui.main_window import MainWindow                        # noqa: E402
from ui.metro_render import normal_dot_screen_r              # noqa: E402

PASS = 0
FAIL = 0


def ok(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}" + (f"   （{extra}）" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"   （{extra}）" if extra else ""))


def pump(n=6):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def set_scale(mv, scale):
    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    pump(8)


def wheel(mv, delta):
    c = mv.viewport().rect().center()
    ev = QWheelEvent(QPointF(c), QPointF(c), QPoint(0, 0), QPoint(0, delta),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    mv.wheelEvent(ev)


def run_once(mv, frozen: bool):
    """跑一次大跨缩放，返回 (合成帧用过的缩放序列, 收尾真实缩放, 收尾真实圆点px)。"""
    set_scale(mv, 0.18)
    c = mv.viewport().rect().center()
    sc = mv.mapToScene(QPoint(c.x(), c.y()))
    # 取离视口中心最近的 3 个**普通站**当样本
    cands = [it for it in mv.station_items.values() if not it.is_transfer]
    cands.sort(key=lambda it: ((it.pos().x() - sc.x()) ** 2
                               + (it.pos().y() - sc.y()) ** 2))
    picks = cands[:3]
    seen = []

    for it in picks:
        orig = it.draw_glyph_screen
        # ★ 变异要用一个**常量**才算"冻住"：直接读 it._view_scale 的话，它在
        #   动画中途可能被收尾逻辑改掉，序列就不是常量了 ⇒ 变异自检自己失效。
        f0 = it._view_scale

        # ★ 实例补丁后 wrap 的**第一个参数是 self**（types.MethodType 的语义），
        #   漏了它就会把 self 当 painter 传进去（实测 AttributeError:
        #   'StationDotItem' object has no attribute 'setBrush'）。
        def wrap(_self, painter, cx, cy, scale, _o=orig, _f=f0):
            # 变异：退回 v2.6.30 的"用冻结的缩放画"（圆点全程不动，松手才跳）
            seen.append(_f if frozen else scale)
            return _o(painter, cx, cy, scale)

        it.draw_glyph_screen = types.MethodType(wrap, it)

    wheel(mv, 1440)                       # 0.18 → ≈1.0（≈5.6×）
    for _ in range(30):
        pump(1)
    mv._zoom_finish.stop()
    mv._apply_station_scale_all()
    pump(20)

    for it in picks:
        try:
            del it.draw_glyph_screen
        except AttributeError:
            pass
    return seen, mv._scale, picks[0].screen_radius()


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

    print("\n===== 合成帧圆点必须跟着虚拟缩放连续变 =====")
    seen, real_scale, real_dot = run_once(mv, frozen=False)
    last = seen[-1] if seen else 0.0
    span = (max(seen) / max(min(seen), 1e-9)) if seen else 1.0
    print(f"      合成帧用过的缩放：n={len(seen)}  末值 {last:.4f}  "
          f"最小 {min(seen):.4f} 最大 {max(seen):.4f}")
    print(f"      收尾真实缩放 {real_scale:.4f}   真实圆点 {real_dot:.2f}px")

    ok("A 合成帧最后一帧用的缩放 == 收尾真实缩放（<2%）",
       abs(last - real_scale) / max(real_scale, 1e-9) < 0.02,
       f"{last:.4f} vs {real_scale:.4f}")
    ok("B 合成帧的缩放**不是常量**（圆点跟着手势连续变，不是冻住）",
       span > 1.05, f"最大/最小 = {span:.2f}×")
    # ★ 2026-10-11：阈值 2.0 → 1.05。滚轮自 v2.7.0 起走**固定档位**，单次滚轮
    #   事件最多推进 3 档（防大跳），所以"一次事件造成的跨度"上限 ≈1.25³≈1.95。
    #   判据本意是"不是常量"（圆点跟着手势连续变），>1.05 足够；
    #   D2 变异自检（冻住 ⇒ 1.00×）仍然会失败 ⇒ 判据依旧在岗。
    ok("C 合成帧算出的圆点半径 == 真实帧半径（<0.5px）",
       abs(normal_dot_screen_r(last) - real_dot) < 0.5,
       f"{normal_dot_screen_r(last):.2f} vs {real_dot:.2f}")

    print("\n===== D 变异自检：退回用冻结的 _view_scale 画 =====")
    seen2, real_scale2, _d = run_once(mv, frozen=True)
    last2 = seen2[-1] if seen2 else 0.0
    span2 = (max(seen2) / max(min(seen2), 1e-9)) if seen2 else 1.0
    print(f"      变异后：末值 {last2:.4f}  最大/最小 = {span2:.2f}×  "
          f"（真实 {real_scale2:.4f}）")
    ok("D1 变异后 A 判据必须失败（否则 A 是摆设）",
       abs(last2 - real_scale2) / max(real_scale2, 1e-9) >= 0.02,
       f"{last2:.4f} vs {real_scale2:.4f}")
    ok("D2 变异后 B 判据必须失败（否则 B 是摆设）",
       span2 <= 2.0, f"最大/最小 = {span2:.2f}×")

    print(f"\n通过 {PASS} 项，失败 {FAIL} 项")
    print("全部通过 ✅" if FAIL == 0 else "★ 有失败项")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
