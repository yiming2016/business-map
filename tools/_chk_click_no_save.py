# -*- coding: utf-8 -*-
"""_chk_click_no_save.py —— 回归：「单击一个站点不该写盘、不该重建线路」。

背景（这是一次真实的数据异常倒查出来的 bug）：
  软件/data/stations.json 里凭空多出两条 _updated_at（罗湖北 04:21:01、
  福坑 04:21:07），坐标一字未改。倒查发现是 tools/verify_anchor_exe.py
  往真机窗口里发了两下【单击】—— 一下打在窗口中心、一下打在 P2。

根因在 ui/metro_render.py 的 StationDotItem.mouseReleaseEvent：
  旧实现只要【左键松手】就 emit station_moved，**不看有没有真的移动**。
  于是"单击选中一个站点"会顺手做完全套：
      _on_station_moved       → upsert_station + save()（147KB+13KB JSON 各写一遍
                                还要各备份一份 .bak）+ rebuild_lines()（重建全部
                                20 条线路几何）+ _refresh_status() + 提示条谎报
                                "已移动「X」→ (x, y)"
      _on_station_moved_internal → _invalidate_nn() + _update_label_visibility()
                                （379 站全量防重叠排版，实测 45~60ms）
  也就是"点一下卡一下"，并且每次点击都把该站的 _updated_at 刷成点击时间。

修法：mousePressEvent 记下按下时的位置，mouseReleaseEvent 里位移
      < STATION_MOVE_EPS(0.05 场景单位) 就直接 return。

本回归四个场景：
  A 真·点击（QTest 打在圆点中心）→ 不许 save / upsert / 全量站名排版
  B 真的拖动          → **必须** save + upsert，且数据里 x/y 同步（防我修过头）
  C 手抖级微动 0.02 场景单位 → 仍按"点击"处理，不落盘
  D 右键点击          → 不落盘

  --mutate-old-release：把 mouseReleaseEvent 换回"无条件 emit"的旧实现，
    用来证明本回归真的抓得住这个 bug（变异测试）。此时 A/C 应当**失败**。

运行：
    python tools/_chk_click_no_save.py
    python tools/_chk_click_no_save.py --mutate-old-release    # 应当失败
"""
from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent

import core.data_manager as DM
from ui import metro_render as MR
from ui.main_window import MainWindow

PASS = FAIL = 0
MICRO = 0.02        # 场景单位：小于 STATION_MOVE_EPS 的"手抖"
REAL_DRAG = 20.0    # 场景单位：明确有意的拖动


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK]   %s   %s" % (name, detail))
    else:
        FAIL += 1
        print("  [FAIL] %s   %s" % (name, detail))


# ---------------------------------------------------------------- 变异
def mutate_old_release() -> None:
    """把 mouseReleaseEvent 还原成"只要左键松手就 emit"的旧实现。"""

    def old_release(self, event):
        MR.QGraphicsObject.mouseReleaseEvent(self, event)
        if event.button() == Qt.LeftButton and self.scene():
            views = self.scene().views()
            if views and hasattr(views[0], "station_moved"):
                views[0].station_moved.emit(self.station_id)

    MR.StationDotItem.mouseReleaseEvent = old_release


# ---------------------------------------------------------------- 造事件
def _ev(item, kind, scene_pos, button=Qt.LeftButton, buttons=Qt.LeftButton):
    e = QGraphicsSceneMouseEvent(kind)
    e.setButton(button)
    e.setButtons(buttons)
    e.setScenePos(scene_pos)
    e.setPos(item.mapFromScene(scene_pos))
    e.setLastScenePos(scene_pos)
    e.setLastPos(item.mapFromScene(scene_pos))
    e.setButtonDownScenePos(button, scene_pos)
    e.setButtonDownPos(button, item.mapFromScene(scene_pos))
    return e


def item_click(item, scene_pos=None):
    """在 item 上发一次"按下+松手、位置完全没变"（= 单击）。"""
    p = scene_pos if scene_pos is not None else item.pos()
    item.mousePressEvent(_ev(item, QEvent.Type.GraphicsSceneMousePress, p))
    item.mouseReleaseEvent(_ev(item, QEvent.Type.GraphicsSceneMouseRelease, p))


def item_drag(item, delta: float, mv=None):
    """按下 → 挪 delta → 松手（模拟真实拖动）。

    ★ 为什么要补一个"零位移的 mouseMoveEvent"：
      真实拖动时，数据里的 x/y 是在 StationDotItem.mouseMoveEvent 里同步的
      （self.data["x"] = round(self.pos().x(), 1)），主窗口 _on_station_moved
      随后又是从 item.data 里取值写盘的。所以"只 setPos 不补移动事件"的话，
      item.data 里的坐标会停留在按下前 —— 那是测试没模拟全，不是程序的问题。
      这里补发一个 scenePos == lastScenePos 的移动事件：Qt 的位移量为 0
      （不会把站点挪两次），但 item.data 会被正确同步成终态。
    """
    p0 = item.pos()
    item.mousePressEvent(_ev(item, QEvent.Type.GraphicsSceneMousePress, p0))
    target = QPointF(p0.x() + delta, p0.y())
    item.setPos(target)                                 # 拖动本体
    item.mouseMoveEvent(_ev(item, QEvent.Type.GraphicsSceneMouseMove, target))
    item.setPos(target)                                 # 兜底：终态必须是 target
    # ★ v2.7.0：**收尾改走 view 层**（与真实鼠标路径一致）。
    #   背景：v2.6.88 起"站点位置的**数据同步** + station_moved 上报"由
    #   `MapView.mouseReleaseEvent` 的收尾分支**确定性**完成（图元只负责视觉位移，
    #   它自己的 release 里有一道 `_move_reported` 去重门）。
    #   本脚本此前直接调图元的 release ⇒ 绕过 view 层收尾，于是
    #   「数据里的 x/y 与图元一致」会失败 —— 那是脚手架没模拟全，不是程序的问题
    #   （真实路径已由 tools/_probe_dragdiff.py 逐步打印验证：差异 0.0）。
    if mv is None:
        item.mouseReleaseEvent(_ev(item, QEvent.Type.GraphicsSceneMouseRelease, target))
        return
    mv._press_dot = item
    mv._press_dot_pos = QPointF(p0)
    mv.mouseReleaseEvent(_ev(item, QEvent.Type.GraphicsSceneMouseRelease, target))


# ---------------------------------------------------------------- 计数
class Counter:
    """把 DataManager.MapView 上几个"昂贵动作"包一层计数，并**照常执行原方法**。

    ★ save 会被真的执行 —— 但落盘目标被临时改到 temp 目录，
      所以既测得准，又不会碰用户的真实数据。
    """

    def __init__(self, win):
        mv = win.map_view
        self.save = self.upsert = self.rebuild = self.layout = 0
        r_save, r_up, r_rb, r_ly = (win.dm.save, win.dm.upsert_station,
                                    mv.rebuild_lines, mv._update_label_visibility)

        def _save(*a, **k):
            self.save += 1
            return r_save(*a, **k)

        def _up(sid, data, *a, **k):
            self.upsert += 1
            return r_up(sid, data, *a, **k)

        def _rb(*a, **k):
            self.rebuild += 1
            return r_rb(*a, **k)

        def _ly(*a, **k):
            self.layout += 1
            return r_ly(*a, **k)

        win.dm.save = _save
        win.dm.upsert_station = _up
        mv.rebuild_lines = _rb
        mv._update_label_visibility = _ly

    def reset(self):
        self.save = self.upsert = self.rebuild = self.layout = 0

    def line(self):
        return "save=%d upsert=%d rebuild_lines=%d 全量排版=%d" % (
            self.save, self.upsert, self.rebuild, self.layout)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate-old-release", action="store_true")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    app.processEvents()
    mv = win.map_view
    # ★ v2.7.0：软件启动即锁定轨迹（用户要求）⇒ 本脚本要先解锁，
    #   否则"拖动站点"这一步全被拦，"不落盘"的断言会假通过。
    win._apply_lock_states(False, False)
    app.processEvents()

    # ★ 测试绝不碰真实数据：把 DataManager 的落盘目标挪到 temp 目录。
    #   （不这么做的话，本脚本的 save 计数会真的写 源码/data/stations.json）
    tmp = Path(tempfile.mkdtemp(prefix="chk_click_"))
    DM.STATIONS_FILE = tmp / "stations.json"
    DM.LINES_FILE = tmp / "lines.json"

    cnt = Counter(win)

    if args.mutate_old_release:
        mutate_old_release()

    print("=" * 78)
    print("视口 %dx%d  站点 %d  线路 %d%s"
          % (mv.viewport().width(), mv.viewport().height(),
             len(mv.station_items), len(mv.line_items),
             "   【变异：mouseReleaseEvent 回到旧实现】"
             if args.mutate_old_release else ""))
    print("落盘目标已改到临时目录：%s" % tmp)
    print("阈值：位移 < %.2f 场景单位 视为「只是点击」" % MR.STATION_MOVE_EPS)

    # 挑一个"当前就在视口里、且有线路"的站点：
    #   ① 有线路 —— 拖动/保存的数据同步看得出来；
    #   ② 在视口里 —— QTest 的点击坐标必须落在视口内才点得到。
    vrect = mv.viewport().rect()
    cands = []
    for k, it in mv.station_items.items():
        if it.scene() is None or not (it.data.get("lines") or []):
            continue
        p = mv.mapFromScene(it.pos())
        if vrect.contains(p):
            cands.append(k)
    if not cands:
        ok("找到「在视口内且有线路」的测试站点", False, "一个都没有")
        print("无法继续，请确认地图已加载数据。")
        return
    sid = cands[len(cands) // 2]
    item = mv.station_items[sid]
    print("测试站点：%s（%s）  位置 (%.1f, %.1f)"
          % (sid, item.data.get("station_name"), item.pos().x(), item.pos().y()))

    # ================================================================
    # A 真·点击（走完整的 QGraphicsView 事件链，最接近用户单击）
    # ================================================================
    print("\nA 单击站点（QTest 打在圆点中心，按/松手位置完全不变）")
    vp = mv.mapFromScene(item.pos())
    # ★ 读的是 DataManager 里"真正会被写盘的那份文档"，不是 item.data
    #   （item.data 在 upsert 后就成了旧对象，拿它比较会看不出变化）
    upd_before = (win.dm.get_station(sid) or {}).get("_updated_at")
    app.processEvents()          # 先把 show/resize 引发的排版排空，免得多算
    cnt.reset()
    QTest.mouseClick(mv.viewport(), Qt.LeftButton, Qt.NoModifier, vp)
    # ★ 立刻读计数：信号是同步发出的，中间不 processEvents，
    #   这样读到的就是"这次点击自己引起的"动作。
    saved, upsed, reb, lay = cnt.save, cnt.upsert, cnt.rebuild, cnt.layout
    ok("A1 单击不落盘（dm.save 不被调用）", saved == 0, "save=%d" % saved)
    ok("A2 单击不 upsert（数据不被改写）", upsed == 0, "upsert=%d" % upsed)
    ok("A3 单击不重建线路", reb == 0, "rebuild_lines=%d" % reb)
    ok("A4 单击不触发 379 站全量排版", lay == 0, "全量排版=%d" % lay)
    upd_after = (win.dm.get_station(sid) or {}).get("_updated_at")
    ok("A5 数据里的 _updated_at 没有被刷成此刻",
       upd_after == upd_before,
       "before=%r after=%r" % (upd_before, upd_after))
    ok("A6 落盘文件根本没被创建", not (tmp / "stations.json").exists(),
       "%s" % (tmp / "stations.json"))
    app.processEvents()

    # ================================================================
    # B 真的拖动 —— 必须照旧落盘（防止修过头）
    # ================================================================
    print("\nB 真正拖动站点 %.0f 场景单位 → 必须落盘" % REAL_DRAG)
    cnt.reset()
    item_drag(item, REAL_DRAG, mv)
    ok("B1 拖动会落盘", cnt.save >= 1, "save=%d" % cnt.save)
    ok("B2 拖动会 upsert", cnt.upsert >= 1, "upsert=%d" % cnt.upsert)
    ok("B3 拖动会重建线路", cnt.rebuild >= 1, "rebuild_lines=%d" % cnt.rebuild)
    stored = win.dm.get_station(sid) or {}
    ok("B4 拖动后数据里的 x/y 与图元一致",
       stored.get("x") == round(item.pos().x(), 1)
       and stored.get("y") == round(item.pos().y(), 1),
       "数据 (%.1f, %.1f) vs 图元 (%.1f, %.1f)"
       % (stored.get("x") or -999, stored.get("y") or -999,
          item.pos().x(), item.pos().y()))
    ok("B5 拖动后 _updated_at 被刷新",
       bool(stored.get("_updated_at")), "_updated_at=%r" % stored.get("_updated_at"))
    # 挪回去，免得影响后面场景的坐标判断
    item.setPos(QPointF(item.pos().x() - REAL_DRAG, item.pos().y()))
    app.processEvents()

    # ================================================================
    # C 手抖级微动（< 阈值）→ 仍按点击处理
    # ================================================================
    print("\nC 按下时手抖 %.2f 场景单位（< 阈值 %.2f）→ 按点击处理"
          % (MICRO, MR.STATION_MOVE_EPS))
    cnt.reset()
    item_drag(item, MICRO)
    ok("C1 微动不落盘", cnt.save == 0, "save=%d" % cnt.save)
    ok("C2 微动不 upsert", cnt.upsert == 0, "upsert=%d" % cnt.upsert)
    item.setPos(QPointF(item.pos().x() - MICRO, item.pos().y()))
    app.processEvents()

    # ================================================================
    # D 右键点击 → 也不该落盘
    # ================================================================
    print("\nD 右键点击站点")
    cnt.reset()
    p = item.pos()
    item.mousePressEvent(_ev(item, QEvent.Type.GraphicsSceneMousePress, p,
                             Qt.RightButton, Qt.RightButton))
    item.mouseReleaseEvent(_ev(item, QEvent.Type.GraphicsSceneMouseRelease, p,
                               Qt.RightButton, Qt.NoButton))
    ok("D1 右键点击不落盘", cnt.save == 0 and cnt.upsert == 0, cnt.line())
    app.processEvents()

    # ================================================================
    # E 成本对比（只打印，不判定）：旧行为下每次误点击白干多少活
    # ================================================================
    print("\nE 旧行为下「单击一次」的额外开销（本机实测，仅参考）")

    def med(fn, n=3):
        ts = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            ts.append((time.perf_counter() - t0) * 1000.0)
        return statistics.median(ts)

    t_layout = med(lambda: (mv._invalidate_nn(), mv._update_label_visibility()))
    t_lines = med(lambda: mv.rebuild_lines())
    t_save = med(lambda: win.dm.save())
    print("  全量站名排版(_invalidate_nn + _update_label_visibility) : %6.1f ms" % t_layout)
    print("  重建全部线路几何(rebuild_lines)                        : %6.1f ms" % t_lines)
    print("  写盘(save：147KB+13KB + 两份 .bak)                      : %6.1f ms" % t_save)
    print("  ────────────────────────────────────────────────────────────")
    print("  合计 ≈ %.1f ms / 每次单击" % (t_layout + t_lines + t_save))
    print("  （修复后：一次单击 = 0 ms，不再有任何落盘/重建/重排版）")

    print("\n" + "=" * 78)
    print("通过 %d 项，失败 %d 项" % (PASS, FAIL))
    if args.mutate_old_release:
        print("（变异模式：这里**应该**看到 A/C 失败，才证明本回归真的抓得住这个 bug）")
    elif FAIL == 0:
        print("全部通过 ✅")
    print("=" * 78)

    win.hide()


if __name__ == "__main__":
    main()
