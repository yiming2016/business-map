# -*- coding: utf-8 -*-
"""
tools/_chk_line_hover.py
========================
回归：**鼠标悬浮在地图上某条线路本身**时，要跟左侧图例悬停同一条线路的效果一致
—— 那条线**加粗**（`screen_width` 4.6 → 8.0）、其余线路**变淡**（opacity 0.18）。

用户原话（v2.6.12）：
    「当鼠标悬浮在某条线路(没悬浮在站点上时)，启用和左侧鼠标悬浮在对应线路时
      的同样效果(即加粗单独只显示这一个线路)」

守三件事：
  A `MetroLineItem.shape()` 必须是**沿路径加粗的带子**，不是 boundingRect 那个大矩形
    ★★ 这是本功能最大的坑：`QGraphicsPathItem` 没重写 `shape()`，默认是整个
       boundingRect —— 一条斜穿全图的线路，bbox 几乎覆盖全屏 ⇒ 鼠标在地图
       **任何地方**都会"命中线路"，悬浮高亮直接变成"一进地图就整屏变"。
  B 端到端（真发鼠标移动）：悬浮 → 加粗+变淡；移开 → 全恢复；**悬浮站点不高亮线路**
  C 不抢点击：线路仍然一个鼠标按键都不接（`Qt.NoButton`）

★ 测试不许写真数据 ⇒ 把 `core.data_manager` 的三个路径指到临时副本
  （`MainWindow.close()` 里有 `dm.save()`，会写回真文件 —— 项目铁律 MEMORY §5.10）。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="v2612hover_"))
for _n in ("stations.json", "lines.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import Qt, QPointF, QEvent          # noqa: E402
from PySide6.QtGui import QPainterPath                  # noqa: E402
from PySide6.QtWidgets import (QApplication,            # noqa: E402
                               QGraphicsSceneHoverEvent)

import ui.metro_render as MR                            # noqa: E402
from ui.main_window import MainWindow                   # noqa: E402

PASS = 0
FAIL = 0
FAILED = []
DEBUG = False


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}" + (f"   （{extra}）" if extra else ""))
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  [FAIL] {name}" + (f"   （{extra}）" if extra else ""))


def pump(n: int = 16) -> None:
    for _ in range(n):
        QApplication.processEvents()


# ---------------------------------------------------------------- 选点
def pick_on_line(mv, lid: str):
    """在这条线路上找一个**没被任何站点包围盒盖住**的场景点。

    ★ 必须避开站点：`StationDotItem` 的 z=10 在线路上方且接受 hover，
      鼠标落在它身上时线路收不到 hoverEnter（这正是用户要的"没悬浮在站点上时"），
      但测试取样如果正好落在站点 bbox 里，就会误判成"悬浮线路没生效"。
    ★★ 不能只试路径顶点：v2.6.18 换乘站变多（圆点更大）+ 折角变少以后，
      超过半数线路的每个顶点都被某个站点的 bbox 盖住 ⇒ 取样恒返回 None，
      判据前提静默失效（"9 条命中"假失败）。顶点找不到就退到**线段中点**
      （站点之间那段路径一定在命中带里，且通常不在任何站点 bbox 内）。
    """
    it = mv.line_items[lid]
    path = it.path()
    boxes = [s.sceneBoundingRect() for s in mv.station_items.values()]

    def free(p: QPointF) -> bool:
        return not any(b.contains(p) for b in boxes)

    pts = []
    for i in range(path.elementCount()):
        e = path.elementAt(i)
        p = QPointF(e.x, e.y)
        if free(p):
            return p
        pts.append(p)
    # 顶点全被站点盖住 ⇒ 试相邻顶点的中点（0.35 / 0.5 / 0.65）
    for a, b in zip(pts, pts[1:]):
        for t in (0.5, 0.35, 0.65):
            p = QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)
            if free(p):
                return p
    return None


def pick_off_line(mv) -> QPointF:
    """找一个**不在任何线路命中带里**的空地点（用来验"移开 → 恢复"）。

    ★★ 这个点必须在**某条线路 boundingRect 之内**：
       `shape()` 的变异就是"换回 boundingRect"。如果空地点取在整个包围盒
       **之外**，连 boundingRect 都命中不了 ⇒ 变异看不出差别，A3 判据假失败
       （第一版就是取 `max(x)+400` 往外扩，变异后照样命中 0 条）。
       正是"包围盒内、路径带外"的这些空白，才是 boundingRect 会误吞的地方。
    """
    boxes = [s.sceneBoundingRect() for s in mv.station_items.values()]
    for it in mv.line_items.values():
        bb = it.sceneBoundingRect()
        if bb.width() < 60 or bb.height() < 60:
            continue
        for i in range(1, 12):
            for j in range(1, 12):
                p = QPointF(bb.left() + bb.width() * i / 12.0,
                            bb.top() + bb.height() * j / 12.0)
                if any(b.contains(p) for b in boxes):
                    continue
                if any(x.shape().contains(p) for x in mv.line_items.values()):
                    continue
                # 再确认它确实在某条线路的 boundingRect 里（变异才会命中它）
                if any(x.sceneBoundingRect().contains(p)
                       for x in mv.line_items.values()):
                    return p
    return QPointF(0.0, 0.0)


_LAST_SCENE_POS: list = [None]      # 上一个鼠标位置（场景坐标）
_HOVERED: list = []                 # 当前处在 hover 中的图元（最多一个）


def _mk_hover(ev_type, cur: QPointF, prev: QPointF):
    ev = QGraphicsSceneHoverEvent(ev_type)
    ev.setScenePos(cur)
    ev.setPos(cur)
    ev.setLastScenePos(prev)
    ev.setLastPos(prev)
    ev.setModifiers(Qt.NoModifier)
    return ev


def _top_hover_item(mv, scene_pt: QPointF):
    """鼠标这点下面、**最上面且接 hover** 的那个图元（没有则 None）。

    ★ 这一步**就是真实的命中测试**：`QGraphicsScene.items()` 走的是
      `item.shape().contains(pos)`，所以 A 组那条「shape 必须是沿路径的带子」
      在 B 组里同样在生效 —— 空地点挑不出线路，线路上才挑得出线路。
    """
    try:
        for it in mv.scene_.items(QPointF(scene_pt)):
            try:
                if it.acceptHoverEvents():
                    return it
            except RuntimeError:
                continue
    except RuntimeError:
        return None
    return None


def move_mouse(mv, scene_pt: QPointF) -> None:
    """在**场景层**模拟一次鼠标移动，双向驱动 hover（进 + 出）。

    ★★★ 三种驱动方式在本环境的实测结果（`tools/_probe_hover2.py`）：

      ① `QTest.mouseMove(viewport, pos)`          —— **完全无效**
         本环境窗口**没有被窗口系统真正映射**（`QApplication.topLevelAt()`
         返回 None、`viewport.WA_Hover = False`），系统级鼠标事件压根
         到不了"场景派发 hover"那一层。已经排除过别的可能：
         `MapView.mouseMoveEvent` **收到了**事件、`super()` 也调了、
         线路 `shape().contains(鼠标点)` 也 = True，可 `_hover` 恒为 False。
      ② `scene.mouseMoveEvent(QGraphicsSceneMouseEvent)` —— **只进不出**
         能触发 hoverEnter（`_hover=True`、线宽 8.0），但**永远不会触发
         hoverLeave** ⇒ 移到空地/站点上，高亮还赖着不走（第一版 3 条失败
         全出在这）。
      ③ `scene.items(pos)` 挑图元 + `scene.sendEvent(item, hover)` —— ✅
         **双向都通**（enter → `_hover=True`；leave → `_hover=False`）。

    所以这里用 ③：它覆盖了「命中测试（`shape()`）→ `hoverEnterEvent/
    hoverLeaveEvent` → `hover_callback` → `MapView._on_line_hover` →
    `highlight_line`」**整条业务链路**，只替换掉「Qt 把一次系统鼠标移动
    翻译成场景 hover 事件」这一跳 —— 那一跳是 Qt 自己的代码，且在无窗口
    映射的环境里本来就走不到。
    ★ 只发给**最上面那一个**接 hover 的图元：这就是 Qt 的规矩，也正是
      用户要的「没悬浮在站点上时」—— 悬浮在站点上时线路收不到 hover。
    """
    scene = mv.scene_
    cur = QPointF(scene_pt)
    prev = _LAST_SCENE_POS[0]
    if prev is None:
        prev = QPointF(cur.x() - 80.0, cur.y() - 80.0)

    top = _top_hover_item(mv, cur)

    # 先给"不再是最上面那个"的发离开（★ 只发一次，别重复）
    for it in list(_HOVERED):
        if it is top:
            continue
        try:
            scene.sendEvent(it, _mk_hover(QEvent.GraphicsSceneHoverLeave,
                                          cur, prev))
        except RuntimeError:
            pass
    # 再给新的发进入
    if top is not None and top not in _HOVERED:
        scene.sendEvent(top, _mk_hover(QEvent.GraphicsSceneHoverEnter,
                                       cur, prev))
    _HOVERED[:] = [top] if top is not None else []
    _LAST_SCENE_POS[0] = cur
    pump(24)
    if DEBUG:
        print("      [dbg] move → %s  top=%s  hovered=%s  widths=%s"
              % (f"({cur.x():.0f},{cur.y():.0f})",
                 type(top).__name__ if top is not None else "None",
                 [type(x).__name__ for x in _HOVERED],
                 sorted(set(round(w, 2) for w in widths(mv).values()))))


def widths(mv) -> dict:
    return {lid: it.screen_width for lid, it in mv.line_items.items()}


def opac(mv) -> dict:
    return {lid: it.opacity() for lid, it in mv.line_items.items()}


def is_rest(mv) -> bool:
    return (all(abs(w - 4.6) < 0.01 for w in widths(mv).values())
            and all(abs(o - 1.0) < 0.01 for o in opac(mv).values()))


# ---------------------------------------------------------------- main
def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(40)
    mv = win.map_view
    mv._apply_zoom_transform(1.0 / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    mv._apply_line_width()
    pump(20)

    lids = sorted(mv.line_items.keys())
    print("\n===== A `shape()` 必须是沿路径的带子，不是 boundingRect =====")
    check("地图里有线路图元（%d 条）" % len(lids), len(lids) >= 10,
          f"{len(lids)} 条")
    # A1 线路自己的顶点必须落在自己的 shape 里
    ok_on = bad_on = 0
    for lid in lids:
        p = pick_on_line(mv, lid)
        if p is None:
            continue
        if mv.line_items[lid].shape().contains(p):
            ok_on += 1
        else:
            bad_on += 1
    check("每条线路上的点都落在自己的 `shape()` 里（命中区确实跟着路径走）",
          bad_on == 0 and ok_on >= 10, f"{ok_on} 条命中、{bad_on} 条没命中")

    # A2 远离所有线路的空地点，**不**该落在任何 shape 里
    off = pick_off_line(mv)
    n_hit_off = sum(1 for it in mv.line_items.values()
                    if it.shape().contains(off))
    check("远离线路的空地点**不**落在任何线路的 `shape()` 里（不会一进地图就整屏变）",
          n_hit_off == 0, f"空地点命中 {n_hit_off} 条")

    # A3 变异：把 shape 换回默认的 boundingRect ⇒ A2 必须失败
    old_shape = MR.MetroLineItem.shape

    def _bbox_shape(self):
        pp = QPainterPath()
        pp.addRect(self.boundingRect())
        return pp

    MR.MetroLineItem.shape = _bbox_shape
    n_hit_bad = sum(1 for it in mv.line_items.values()
                    if it.shape().contains(off))
    check("变异（`shape()` 换回 boundingRect）后空地点被大量线路命中 ⇒ A2 判据真在上岗",
          n_hit_bad > 0, f"变异后命中 {n_hit_bad} 条")
    MR.MetroLineItem.shape = old_shape
    # 清掉缓存，让后续用到新的 shape
    for it in mv.line_items.values():
        it._shape_cache = None

    print("\n===== B 端到端：真发鼠标移动 =====")
    # B0 起点：静止态
    move_mouse(mv, off)
    check("鼠标在空地上：全部恢复（线宽 4.6 / 不透明）", is_rest(mv),
          "线宽 %s" % sorted(set(round(w, 2) for w in widths(mv).values())))

    # B1 悬浮到某条线路上
    target = None
    for lid in lids:
        p = pick_on_line(mv, lid)
        if p is None:
            continue
        mv.centerOn(p)
        pump(16)
        move_mouse(mv, p)
        if abs(mv.line_items[lid].screen_width - 8.0) < 0.01:
            target = lid
            break
    check("悬浮到线路上：那条线**加粗**（4.6 → 8.0）", target is not None,
          f"命中 {target}")
    if target is not None:
        others = [o for lid2, o in opac(mv).items() if lid2 != target]
        check("悬浮到线路上：其余线路**变淡**（opacity 0.18）",
              others and all(abs(o - 0.18) < 0.01 for o in others),
              f"其余 {len(others)} 条，opacity %s"
              % sorted(set(round(o, 3) for o in others)))
        check("悬浮到线路上：那条线自己是**全不透明**",
              abs(mv.line_items[target].opacity() - 1.0) < 0.01,
              f"{mv.line_items[target].opacity():.2f}")

    # B2 移开 → 恢复
    off2 = pick_off_line(mv)
    mv.centerOn(off2)
    pump(16)
    move_mouse(mv, off2)
    check("鼠标移开线路：全部恢复（不留高亮）", is_rest(mv),
          "线宽 %s" % sorted(set(round(w, 2) for w in widths(mv).values())))

    # B3 ★ 悬浮到**站点**上时，不许高亮任何线路
    sid = next(iter(mv.station_items.keys()))
    sit = mv.station_items[sid]
    mv.centerOn(QPointF(sit.pos()))
    pump(16)
    move_mouse(mv, QPointF(sit.pos()))
    check("悬浮在**站点**上：站点自己有 hover 反馈", bool(sit._hover),
          f"{sid}._hover={sit._hover}")
    check("悬浮在**站点**上：**不**高亮任何线路（用户要的'没悬浮在站点上时'）",
          is_rest(mv),
          "线宽 %s" % sorted(set(round(w, 2) for w in widths(mv).values())))

    # B4 变异：不接 hover 事件 ⇒ 悬浮线路没反应
    old_init = MR.MetroLineItem.__init__

    def _no_hover_init(self, *a, **k):
        old_init(self, *a, **k)
        self.setAcceptHoverEvents(False)

    p2 = pick_on_line(mv, target or lids[0])
    mv.centerOn(p2)
    pump(16)
    MR.MetroLineItem.__init__ = _no_hover_init
    mv.rebuild_lines()
    pump(20)
    _HOVERED.clear()                 # 图元已重建，旧引用作废
    move_mouse(mv, p2)
    check("变异（不接 hover 事件）后悬浮线路**没有**加粗 ⇒ B1 判据真在上岗",
          is_rest(mv),
          "变异后线宽 %s" % sorted(set(round(w, 2) for w in widths(mv).values())))
    MR.MetroLineItem.__init__ = old_init
    mv.rebuild_lines()
    pump(20)
    _HOVERED.clear()

    # B5 变异：**那一条线路实例**的 `hoverLeaveEvent` 不通知回调 ⇒
    #    "移开 → 恢复"必须失败
    #    ★ 这条是专门盯 **离开** 那一半的：B4 只盯了"接不接 hover"，
    #      如果哪天 `hoverLeaveEvent` 被改坏（比如把回调删了），
    #      只靠 B4 是抓不到的 —— 高亮会永远赖在屏幕上退不出来。
    # ★★ 用**实例级**打补丁（`types.MethodType`），**不能**在类上换：
    #    PySide6 的类级虚方法替换是**单向**的 —— 实测"换上去生效、换回来
    #    不生效"（换回来后 leave 依旧走变异体，判据假失败）。
    #    这是项目铁律 §4.5 同一个坑的另一个面：类级换虚方法根本靠不住，
    #    一律 `types.MethodType(f, obj)` 打到实例上，还原用 `del obj.f`。
    it2 = mv.line_items[target]

    def _mute_leave(self, event):
        self._hover = False          # 只清自己，不通知 MapView

    move_mouse(mv, off)
    it2.hoverLeaveEvent = types.MethodType(_mute_leave, it2)
    _HOVERED.clear()
    move_mouse(mv, p2)
    entered = not is_rest(mv)
    move_mouse(mv, off)
    still = not is_rest(mv)
    del it2.hoverLeaveEvent          # 还原：实例属性删掉就回到类上的真方法
    # ★ 变异期间高亮被"卡住"了（画面还亮着，可 `_HOVERED` 已经空了），
    #   还原后光 `move_mouse(off)` 是空操作（没有"要离开谁"），
    #   必须**重新进入一次再离开**才会真的走到 leave。
    _HOVERED.clear()
    move_mouse(mv, p2)
    move_mouse(mv, off)
    check("变异（`hoverLeaveEvent` 不通知回调）后移开**不恢复** ⇒ B2 判据真在上岗",
          entered and still, f"悬浮生效={entered}，移开后仍高亮={still}")
    check("还原后移开能恢复", is_rest(mv),
          "线宽 %s" % sorted(set(round(w, 2) for w in widths(mv).values())))

    # B5 隔离状态下悬浮线路要让位（和左侧图例悬停一个规矩）
    if target is not None:
        mv.set_isolated_line(target)
        pump(20)
        move_mouse(mv, p2)
        check("已经处于「单独显示」时，再悬浮线路**不**改画面（让位给隔离）",
              all(abs(o - 1.0) < 0.01 for o in opac(mv).values()),
              "opacity %s" % sorted(set(round(o, 2) for o in opac(mv).values())))
        mv.set_isolated_line("")
        pump(20)

    print("\n===== C 不抢点击 =====")
    check("线路**一个鼠标按键都不接**（不挡点空白拖地图 / 点站点）",
          all(it.acceptedMouseButtons() == Qt.NoButton
              for it in mv.line_items.values()),
          "全部 NoButton")
    check("线路**只**接 hover（`ItemIsSelectable/Movable` 都关着）",
          all(not it.flags() & MR.QGraphicsItem.ItemIsSelectable
              and not it.flags() & MR.QGraphicsItem.ItemIsMovable
              for it in mv.line_items.values()),
          "selectable/movable 均为关")

    # C3 ★ 线路不许盖住站点：站点圆心处，"最上面可交互"的必须是站点而不是线路。
    #   （不用 QTest.mouseClick —— 那要依赖视口坐标/居中时机，测出来的是
    #     测试环境而不是被测代码；命中顺序才是"会不会挡住点击"的本质。）
    top = None
    for it in mv.scene_.items(QPointF(sit.pos())):
        if it.flags() & MR.QGraphicsItem.ItemIsSelectable or it is sit:
            top = it
            break
    check("站点圆心处最上面的可交互图元**是站点**（线路 z=-5 不会挡住点站点）",
          top is sit, f"最上面 = {type(top).__name__}")
    check("线路图元的 z 值低于站点（叠放顺序上在线路下面）",
          all(it.zValue() < 0 for it in mv.line_items.values())
          and sit.zValue() > 0,
          f"线路 z={sorted(set(it.zValue() for it in mv.line_items.values()))}, "
          f"站点 z={sit.zValue()}")

    print("\n===== 结果：%d 通过 / %d 失败 =====" % (PASS, FAIL))
    if FAILED:
        print("失败项：")
        for n in FAILED:
            print("  - " + n)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
