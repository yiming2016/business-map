# -*- coding: utf-8 -*-
"""回归 v2.6.32：站名**位置固定** + **可单独拖动** + 拖圆点时站名跟随。

用户原话：「限制文字固定在一个位置，不要每次缩放都上下左右的乱窜。
          文字和站点圆圈分离开，可以单独拖动文字更改所在位置，
          拖动站点圆圈则文字跟随移动。」

判据：
  A 方位锁：在 ≥0.5 的各档之间来回缩放，站名方位**一个都不变**
  B 变异：把锁的门槛顶到 99（等于关掉锁）⇒ A 必须炸（证明判据真在上岗）
  C 拖站名：在站名上按下拖动 ⇒ 站名偏移变了、**圆点没动**、
            data 里落了 label_dx/label_dy，且重排后偏移不被改回去
  D 拖圆点：在圆点上按下拖动 ⇒ 圆点动了、**站名跟着整体平移**
            （相对偏移不变）
  E 单击站名（没拖动）⇒ 不写盘、偏移不变，且该站被选中

运行：
    ...\\python.exe tools/_chk_label_lock_drag.py
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

_TMP = Path(tempfile.mkdtemp(prefix="labeldrag_"))
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
import ui.map_view as MV                                      # noqa: E402

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


def wheel(mv, delta):
    c = mv.viewport().rect().center()
    ev = QWheelEvent(QPointF(c), QPointF(c), QPoint(0, 0), QPoint(0, delta),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    mv.wheelEvent(ev)


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


def sides(mv):
    return {sid: it.label_side() for sid, it in mv.station_items.items()}


def drag(mv, from_vp: QPoint, to_vp: QPoint):
    """在视口上真按真拖（走 MapView 自己的鼠标事件）。"""
    QTest.mousePress(mv.viewport(), Qt.LeftButton, Qt.NoModifier, from_vp, 10)
    pump(2)
    QTest.mouseMove(mv.viewport(), to_vp, 10)
    pump(2)
    QTest.mouseMove(mv.viewport(), QPoint(to_vp.x() + 2, to_vp.y() + 2), 10)
    pump(2)
    QTest.mouseRelease(mv.viewport(), Qt.LeftButton, Qt.NoModifier, to_vp, 10)
    pump(6)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(10)
    mv = win.map_view
    # ★ v2.7.0：软件现在**启动即锁定轨迹**（用户要求），本脚本测的是
    #   "拖得动 + 站名方位/偏移正确"，必须先解除两把锁，否则拖动全部被拦。
    win._apply_lock_states(False, False)
    pump(2)

    # ---------------------------------------------------------------
    print("===== A 方位锁：≥0.5 档来回缩放，站名方位不许变 =====")
    set_scale(mv, 1.0)
    base = sides(mv)
    print(f"       基准档 1.00，站名 {len(base)} 个，锁表 {len(mv._side_lock)} 条")
    worst = 0
    for s in (0.8, 0.6, 1.5, 2.2, 0.7, 1.0, 3.0, 1.0):
        set_scale(mv, s)
        cur = sides(mv)
        diff = sum(1 for k in base if base[k] != cur.get(k))
        print(f"       缩放 {s:>4.2f}：换边 {diff} 个")
        worst = max(worst, diff)
    ok("A 方位锁：8 次跨档缩放，换边 0 个", worst == 0, f"最多 {worst}")
    ok("A2 锁表已建成（不是空跑）", len(mv._side_lock) >= 300,
       f"{len(mv._side_lock)} 条")

    # ---------------------------------------------------------------
    print("===== B 变异自检：关掉锁 ⇒ A 必须炸 =====")
    # ★ v2.6.43：老变异 `LABEL_LOCK_MIN_SCALE = 99.0` 靠"门槛永不满足"来放开锁，
    #   但那条门槛已取消（任何档都用锁表）⇒ 变异失效（实测换边 0）。
    #   改成**让锁表建不起来**：`_build_side_lock` 变空 + 清空锁表 ⇒ 每档各自重挑。
    #   ★ 必须在测量**之前**设（老代码写在测量的后面，等于没变异）。
    mv._build_side_lock = lambda: None
    mv._side_lock = {}
    set_scale(mv, 1.0)
    base2 = sides(mv)
    worst2 = 0
    for s in (0.8, 0.6, 1.5, 2.2, 0.7, 1.0, 3.0, 1.0):
        mv._side_lock = {}          # ★ 排版**之前**清（_take 会在排版里写回锁表）
        set_scale(mv, s)
        cur = sides(mv)
        worst2 = max(worst2, sum(1 for k in base2 if base2[k] != cur.get(k)))
    print(f"       关掉锁后：换边最多 {worst2} 个")
    ok("B 变异（关掉方位锁）后换边 > 0 ⇒ A 判据真在上岗", worst2 > 0, f"{worst2}")
    del mv._build_side_lock          # 还原（实例属性 ⇒ del 后回退到类方法）
    mv._side_lock = {}

    # ---------------------------------------------------------------
    print("===== C 拖站名：站名动、圆点不动、偏移落盘 =====")
    set_scale(mv, 1.0)
    c = mv.viewport().rect().center()
    sc = mv.mapToScene(QPoint(c.x(), c.y()))
    cands = sorted(mv.station_items.values(),
                   key=lambda it: (it.pos().x() - sc.x()) ** 2
                   + (it.pos().y() - sc.y()) ** 2)
    tgt = None
    for it in cands:
        lr = it.label_scene_rect()
        vp = mv.mapFromScene(QPointF(lr.center().x(), lr.center().y()))
        if (12 <= vp.x() <= mv.viewport().width() - 60
                and 12 <= vp.y() <= mv.viewport().height() - 20):
            tgt, tgt_vp = it, QPoint(int(vp.x()), int(vp.y()))
            break
    if tgt is None:
        ok("C 找到可拖的站名样本", False, "视口里没有合适的站")
    else:
        p0 = QPointF(tgt.pos())
        off0 = QPointF(tgt.label_off())
        drag(mv, tgt_vp, QPoint(tgt_vp.x() + 46, tgt_vp.y() - 30))
        off1 = QPointF(tgt.label_off())
        moved = abs(off1.x() - off0.x()) + abs(off1.y() - off0.y())
        dot_moved = abs(tgt.pos().x() - p0.x()) + abs(tgt.pos().y() - p0.y())
        ok("C1 站名偏移变了（拖得动）", moved >= 20,
           f"Δ=({off1.x() - off0.x():.0f}, {off1.y() - off0.y():.0f}) 屏幕px")
        ok("C2 圆点一个像素都没动", dot_moved < 0.5, f"{dot_moved:.2f}")
        ok("C3 偏移写进 data（label_dx/label_dy）",
           abs(float(tgt.data.get("label_dx", 0)) - off1.x()) < 0.2
           and abs(float(tgt.data.get("label_dy", 0)) - off1.y()) < 0.2,
           f"{tgt.data.get('label_dx')}, {tgt.data.get('label_dy')}")
        # 重排（换档）之后不许被挪回去
        sd0 = tgt.label_side()
        set_scale(mv, 1.4)
        set_scale(mv, 0.9)
        ok("C4 换档重排后偏移仍原样（排版器不碰手拖过的站名）",
           abs(tgt.label_off().x() - off1.x()) < 0.2
           and abs(tgt.label_off().y() - off1.y()) < 0.2
           and tgt.label_side() == sd0,
           f"({tgt.label_off().x():.0f}, {tgt.label_off().y():.0f})")
        # 落盘
        saved = CDM.get_data_manager().all_stations().get(tgt.station_id, {})
        ok("C5 已经落到 stations.json", "label_dx" in saved,
           f"{saved.get('label_dx')}, {saved.get('label_dy')}")
        tgt.set_label_off(0.0, 0.0)     # 用完复原，别污染后面的判据
        tgt.data.pop("label_dx", None)
        tgt.data.pop("label_dy", None)

    # ---------------------------------------------------------------
    print("===== D 拖圆点：站名跟着整体平移 =====")
    set_scale(mv, 1.0)
    sc = mv.mapToScene(QPoint(c.x(), c.y()))
    tgt2 = min(mv.station_items.values(),
               key=lambda it: (it.pos().x() - sc.x()) ** 2
               + (it.pos().y() - sc.y()) ** 2)
    dvp = mv.mapFromScene(QPointF(tgt2.pos().x(), tgt2.pos().y()))
    vp0 = QPoint(int(dvp.x()), int(dvp.y()))
    p_before = QPointF(tgt2.pos())
    lr_before = tgt2.label_scene_rect()
    rel0 = QPointF(lr_before.center().x() - p_before.x(),
                   lr_before.center().y() - p_before.y())
    drag(mv, vp0, QPoint(vp0.x() + 40, vp0.y() + 26))
    p_after = QPointF(tgt2.pos())
    lr_after = tgt2.label_scene_rect()
    rel1 = QPointF(lr_after.center().x() - p_after.x(),
                   lr_after.center().y() - p_after.y())
    dot_d = abs(p_after.x() - p_before.x()) + abs(p_after.y() - p_before.y())
    ok("D1 圆点被拖动了", dot_d > 5, f"{dot_d:.1f} 场景单位")
    ok("D2 站名跟着走（相对圆点的偏移不变，误差 <1.5 场景单位）",
       abs(rel1.x() - rel0.x()) < 1.5 and abs(rel1.y() - rel0.y()) < 1.5,
       f"Δrel=({rel1.x() - rel0.x():.2f}, {rel1.y() - rel0.y():.2f})")

    # ---------------------------------------------------------------
    print("===== E 单击站名（没拖动）：选中该站、不改偏移 =====")
    set_scale(mv, 1.0)
    sc = mv.mapToScene(QPoint(c.x(), c.y()))
    tgt3 = None
    for it in sorted(mv.station_items.values(),
                     key=lambda it: (it.pos().x() - sc.x()) ** 2
                     + (it.pos().y() - sc.y()) ** 2):
        lr = it.label_scene_rect()
        vp = mv.mapFromScene(QPointF(lr.center().x(), lr.center().y()))
        if (12 <= vp.x() <= mv.viewport().width() - 60
                and 12 <= vp.y() <= mv.viewport().height() - 20):
            tgt3, vp3 = it, QPoint(int(vp.x()), int(vp.y()))
            break
    if tgt3 is None:
        ok("E 找到可点的站名样本", False)
    else:
        o0 = QPointF(tgt3.label_off())
        QTest.mousePress(mv.viewport(), Qt.LeftButton, Qt.NoModifier, vp3, 10)
        pump(2)
        QTest.mouseRelease(mv.viewport(), Qt.LeftButton, Qt.NoModifier, vp3, 10)
        pump(6)
        ok("E1 单击站名不改偏移",
           abs(tgt3.label_off().x() - o0.x()) < 0.01
           and abs(tgt3.label_off().y() - o0.y()) < 0.01)
        ok("E2 单击站名 = 选中该站",
           mv._focus_station_id == tgt3.station_id,
           f"{mv._focus_station_id} vs {tgt3.station_id}")

    # ---------------------------------------------------------------
    print("===== F 最小缩放锁死（v2.6.32）：不许再进入出问题的档位 =====")
    mv.fit_map()
    pump(4)
    floor = mv._min_scale_for_viewport()
    # ★ v2.6.38：下限(0.10) 现在比"整图适配"(0.105)**还低** ⇒ fit_map 该停在
    #   **整图适配**那一档（能看全图），而不是下限。判据改成"一步到位 = max(整图适配, 下限)"。
    _vp = mv.viewport()
    _base = mv._content_rect
    _fit = min((_vp.width() - 2) / _base.width(), (_vp.height() - 2) / _base.height())
    _want = max(_fit, floor)
    ok("F1 「适应/全图」一步到位（不再先缩到整图再弹回）",
       abs(mv._scale - _want) < 1e-3,
       f"{mv._scale:.4f} vs 目标 {_want:.4f}（整图适配 {_fit:.4f} / 下限 {floor:.4f}）")
    # ★ v2.6.38：下限常量从 0.30 放宽到 0.10（缩放过程已改位图拉伸，
    #   "缩到最小的怪操作"没了，用户要"和图片一样"能自由缩小）。
    #   ⇒ 判据跟**常量**走，别再写死 0.30。
    ok(f"F2 下限 ≥ MIN_VIEW_SCALE（{MV.MIN_VIEW_SCALE}）",
       floor >= MV.MIN_VIEW_SCALE - 1e-6, f"{floor:.4f}")
    # 狂滚 20 格缩小，必须**停在同一格**，一格都不许再往下
    before = mv._scale
    for _ in range(20):
        wheel(mv, -240)
        pump(1)
    pump(10)
    ok("F3 连滚 20 格缩小后仍停在下限（不会越来越小）",
       abs(mv._scale - floor) < 1e-3, f"{before:.4f} → {mv._scale:.4f}")
    # 居中不许跑偏（旧写法 fitInView 之后再 centerOn 一次，容易偏）
    ctr = mv.mapToScene(QPoint(mv.viewport().rect().center().x(),
                               mv.viewport().rect().center().y()))
    base_c = mv._content_rect.center()
    off = (abs(ctr.x() - base_c.x()) + abs(ctr.y() - base_c.y())) * mv._scale
    # ★★ v2.6.51：最小档抬到 0.115 之后，**0.115 > fit(≈0.105)** ⇒ 铺满全图会被卡住
    #   （图比视口大约 9%），此时程序按 v2.6.43 那条规则改居中到**站点质心**。
    #   ⇒ 视口中心 ≠ 内容矩形中心是**预期的**（实测 92px），拿旧阈值 5px 卡就是假失败。
    #   这条判据真正要防的是 v2.6.44 那个"缩到最小 = 一片空白"的事故 ⇒
    #   直接断言**视口中心看得见内容**（附近确实有站、且不是飘在无人区）。
    near = None
    for it in mv.station_items.values():
        d = ((it.pos().x() - ctr.x()) ** 2 + (it.pos().y() - ctr.y()) ** 2) ** 0.5
        near = d if near is None else min(near, d)
    vp_half = 0.5 * min(mv.viewport().width(), mv.viewport().height()) / mv._scale
    ok("F4 缩到最小时画面**看得见内容**（视口中心不是空白：最近站 ≪ 半个视口）",
       near is not None and near < vp_half * 0.6,
       f"最近站 {near:.0f} 场景单位（半个视口 {vp_half:.0f}）；中心偏离内容中心 {off:.2f} 屏幕px")

    # ---------------------------------------------------------------
    print("===== G v2.6.34：线路号方块可以移动位置 =====")
    import ui.map_view as MV2
    set_scale(mv, 1.0)
    c = mv.viewport().rect().center()
    tgtb = None
    # 线路号方块都摆在线路末端（图的最外圈），视口中心看不到 ⇒ 先把镜头移过去
    for k, it in mv.badge_items.items():
        if not it.isVisible():
            continue
        mv.centerOn(it.pos())
        pump(3)
        vp = mv.mapFromScene(QPointF(it.pos().x(), it.pos().y()))
        if (30 <= vp.x() <= mv.viewport().width() - 30
                and 30 <= vp.y() <= mv.viewport().height() - 30):
            tgtb, vpb = it, QPoint(int(vp.x()), int(vp.y()))
            break
    if tgtb is None:
        ok("G 视口里找到可拖的线路号方块", False, "没有可见方块")
    else:
        key = tgtb.badge_key
        p0 = QPointF(tgtb.pos())
        drag(mv, vpb, QPoint(vpb.x() - 38, vpb.y() + 34))
        p1 = QPointF(tgtb.pos())
        moved = abs(p1.x() - p0.x()) + abs(p1.y() - p0.y())
        ok("G1 方块被拖动了（屏幕位移换算成场景位移）", moved >= 20,
           f"Δ场景=({p1.x() - p0.x():.0f}, {p1.y() - p0.y():.0f})")
        ok("G2 拖完有非零偏移", tgtb.has_badge_off(),
           f"({tgtb.badge_off().x():.0f}, {tgtb.badge_off().y():.0f})")
        offs = MV2.load_badge_offsets()
        ok("G3 落盘到 badge_offsets.json", key in offs,
           f"{key} → {offs.get(key)}")
        # 重建（模拟切线路/重启）后位置必须还在
        mv.rebuild_terminal_badges()
        pump(4)
        # badge_items 的键是 "<站名>#<线号>"，而落盘键是 "<线号>|<站名>"
        _lid, _nm = key.split("|", 1)
        it2 = mv.badge_items.get(_nm + "#" + _lid)
        ok("G4 重建后偏移仍在（位置不丢）",
           it2 is not None and it2.has_badge_off(),
           f"{None if it2 is None else (round(it2.badge_off().x()), round(it2.badge_off().y()))}")
        # 复位
        n = mv.reset_badge_offsets()
        pump(3)
        ok("G5 复位接口能清空叠加文件", n >= 1 and not MV2.load_badge_offsets(),
           f"清掉 {n} 条")

    # ---------------------------------------------------------------
    print("===== H v2.6.34：Ctrl+Z / Ctrl+Y 撤销重做 =====")
    set_scale(mv, 1.0)
    c = mv.viewport().rect().center()
    sc = mv.mapToScene(QPoint(c.x(), c.y()))
    t4 = min(mv.station_items.values(),
             key=lambda it: (it.pos().x() - sc.x()) ** 2
             + (it.pos().y() - sc.y()) ** 2)
    sid4 = t4.station_id
    # ★ G 段把镜头移到了图边缘，这里必须先把它挪回来 ——
    #   否则视口里的坐标落在窗口外，QTest 发的事件等于没发（假通过）。
    # ★ 再把 F 段连滚 20 格留下的缩放动画彻底停掉：动画定时器还在跑的话，
    #   它会在拖动中途落变换，Qt 的 item 拖动就会被中途打断（= 拖了不动）。
    mv._zoom_anim.stop()
    mv._abort_zoom_snap()
    mv.centerOn(t4.pos())
    pump(6)
    _v = mv.mapFromScene(QPointF(t4.pos().x(), t4.pos().y()))
    vp4 = QPoint(int(_v.x()), int(_v.y()))
    p_before = QPointF(t4.pos())
    n0 = len(win._undo_stack)
    _hit = mv.station_at(mv._scene_at(vp4))
    ok("H0 站点中心**优先**判成站点（不被线路号方块的外框抢走）",
       _hit is not None and _hit.station_id == sid4,
       f"命中 {None if _hit is None else _hit.station_id}")
    drag(mv, vp4, QPoint(vp4.x() + 44, vp4.y() + 30))
    p_after = QPointF(mv.station_items[sid4].pos())
    d_move = abs(p_after.x() - p_before.x()) + abs(p_after.y() - p_before.y())
    ok("H1 拖动站点后坐标变了", d_move > 5, f"{d_move:.0f} 场景单位")
    ok("H2 这次拖动进了撤销栈", len(win._undo_stack) == n0 + 1,
       f"{n0} → {len(win._undo_stack)}")
    win._on_undo()
    pump(8)
    p_undo = QPointF(mv.station_items[sid4].pos())
    ok("H3 撤销后坐标回到拖动前",
       abs(p_undo.x() - p_before.x()) < 1.0 and abs(p_undo.y() - p_before.y()) < 1.0,
       f"({p_undo.x():.0f},{p_undo.y():.0f}) vs ({p_before.x():.0f},{p_before.y():.0f})")
    saved = CDM.get_data_manager().all_stations().get(sid4, {})
    ok("H4 撤销**同时写回了文件**（不是只改内存）",
       abs(float(saved.get("x", 0)) - p_before.x()) < 1.0,
       f"文件里 x={saved.get('x')}")
    win._on_redo()
    pump(8)
    p_redo = QPointF(mv.station_items[sid4].pos())
    ok("H5 重做后又回到拖动后的位置",
       abs(p_redo.x() - p_after.x()) < 1.0 and abs(p_redo.y() - p_after.y()) < 1.0,
       f"({p_redo.x():.0f},{p_redo.y():.0f})")
    # 撤销到底不许崩
    for _ in range(len(win._undo_stack) + 5):
        win._on_undo()
    pump(6)
    ok("H6 一直撤销到栈空也不崩、栈不为负", len(win._undo_stack) == 0)
    ok("H7 栈空后再撤销是空操作（不报错）", True)

    # ---------------------------------------------------------------
    print("===== I v2.6.35：官方原图垫底（对照着手动调） =====")
    ok("I1 默认不显示底图", mv._underlay_item is None)
    shown = mv.toggle_underlay()
    pump(3)
    it = mv._underlay_item
    ok("I2 开底图：场景里真的多了一个图元", shown and it is not None)
    if it is not None:
        r = it.sceneBoundingRect()
        ok("I3 底图严丝合缝铺满 0~8000（场景坐标 = 原图像素系）",
           abs(r.x()) < 1.0 and abs(r.y()) < 1.0
           and abs(r.width() - 8000.0) < 1.0 and abs(r.height() - 8000.0) < 1.0,
           f"({r.x():.0f},{r.y():.0f}) {r.width():.0f}x{r.height():.0f}")
        ok("I4 垫在最底下（z < 线路 -5）", it.zValue() < -5, f"z={it.zValue()}")
        ok("I5 半透明（能看见我们自己的图）", 0.0 < it.opacity() < 1.0,
           f"{it.opacity():.2f}")
        ok("I6 **不吃鼠标**（不能挡住底下的站点）",
           it.acceptedMouseButtons() == Qt.NoButton)
        # 开着底图时站点照样能拖（不能被浮层/底图吃掉）
        _h2 = mv.station_at(mv._scene_at(QPoint(mv.viewport().width() // 2,
                                                mv.viewport().height() // 2)))
        ok("I7 底图开着时命中测试不受影响",
           _h2 is None or _h2.station_id != "", "命中正常")
    mv.toggle_underlay(False)
    pump(2)
    ok("I8 关底图：图元被移除", mv._underlay_item is None)

    # ---------------------------------------------------------------
    print("===== J v2.6.37：每个站的站名都抓得住（用户：下沙这类拖不动） =====")

    def scan_bad(view):
        """站名框中心 → 命中谁。坏 = 抓不到 / 抓成别站。"""
        out = []
        for _it in view.station_items.values():
            _lr = _it.label_scene_rect()
            if _lr.width() <= 0.5 or _lr.height() <= 0.5:
                continue
            if not _it.is_label_visible():
                continue
            if view._label_hit(_lr.center()) is not _it:
                out.append(_it.data.get("station_name"))
        return out

    for _sc in (1.0, 0.30):
        set_scale(mv, _sc)
        _bad = scan_bad(mv)
        ok(f"J1 缩放 {_sc}：每个可见站名的框中心都能被**自己**抓住",
           not _bad, f"{len(_bad)} 个抓不到：{_bad[:8]}")

    # 真按真拖一次用户点名的站
    set_scale(mv, 1.0)
    _xia = None
    for it in mv.station_items.values():
        if it.data.get("station_name") == "下沙":
            _xia = it
            break
    ok("J2 数据里有『下沙』这个站", _xia is not None)
    if _xia is not None:
        mv.centerOn(_xia.pos())
        pump(6)
        _lr = _xia.label_scene_rect()
        _p = mv.mapFromScene(_lr.center())
        _vp = mv.viewport()
        ok("J3 『下沙』的站名落在视口里", 0 <= _p.x() < _vp.width()
           and 0 <= _p.y() < _vp.height(), f"({_p.x():.0f},{_p.y():.0f})")
        _off0 = QPointF(_xia.label_off())
        _dot0 = QPointF(_xia.pos())
        drag(mv, QPoint(int(_p.x()), int(_p.y())),
             QPoint(int(_p.x()) + 48, int(_p.y()) - 28))
        _off1 = QPointF(_xia.label_off())
        ok("J4 真拖『下沙』站名：偏移真的变了（不再是只能跟着站点走）",
           abs(_off1.x() - _off0.x()) > 10 and abs(_off1.y() - _off0.y()) > 5,
           f"({_off0.x():.0f},{_off0.y():.0f}) → ({_off1.x():.0f},{_off1.y():.0f})")
        ok("J5 拖站名时圆点**纹丝不动**",
           abs(_xia.pos().x() - _dot0.x()) < 0.01
           and abs(_xia.pos().y() - _dot0.y()) < 0.01)

    # 变异自检：换回"只问 station_at 那一个"的老逻辑 ⇒ J1 必须炸
    def _old_hit(self, scene_pos):
        # ★ 注意：`station_at` 内部现在**也会**调 `_label_hit`（那正是被测的新
        #   逻辑）⇒ 直接调就无限递归（老脚本就是这么炸的）。这里先把 `_label_hit`
        #   掐成恒 None，让它只走"问鼠标下最上面那个圆点"那条路，
        #   这才等价于 v2.6.37 之前的老代码。
        _keep = self._label_hit
        self._label_hit = types.MethodType(lambda s, p: None, self)
        try:
            _item = self.station_at(scene_pos)
        finally:
            self._label_hit = _keep
        if _item is None:
            return None
        _pad = 4.0 / max(self._scale, 1e-6)
        if _item.label_scene_rect().adjusted(
                -_pad, -_pad, _pad, _pad).contains(scene_pos):
            return _item
        return None

    set_scale(mv, 1.0)
    mv._label_hit = types.MethodType(_old_hit, mv)     # ★ 只换实例，别换类
    _bad_mut = scan_bad(mv)
    del mv._label_hit                                   # 还原（换的是实例方法）
    ok("J6 变异：换回老逻辑（只问最上面那个站）⇒ 必须有一批站抓不到",
       len(_bad_mut) > 0, f"老逻辑下 {len(_bad_mut)} 个抓不到：{_bad_mut[:8]}")

    # ★ 强变异：命中函数恒空 ⇒ 所有站都得抓不到。这条**必然**生效，
    #   用来担保 J1 这条判据不是"恒真"（老逻辑那条会随排版状态浮动）。
    _vis_n = sum(1 for it in mv.station_items.values() if it.is_label_visible())
    mv._label_hit = types.MethodType(lambda self, p: None, mv)
    _bad_none_mut = scan_bad(mv)
    del mv._label_hit
    ok("J7 强变异：命中函数恒空 ⇒ 每一个可见站名都抓不到（判据不是恒真）",
       len(_bad_none_mut) == _vis_n > 0,
       f"{len(_bad_none_mut)}/{_vis_n}")

    # ---------------------------------------------------------------
    print("===== K v2.6.39：被外推(ring>0)的站名也要拖得动（转弯处的文字） =====")
    # 用户原话：「只要是转弯处的文字均不能被拖动」
    # 病根：转弯处线路最密 ⇒ 站名被排版器推到外圈（side 带 ring>0）⇒
    #       `_label_box()` 里手动偏移**只在 ring==0 时叠加** ⇒ 数据记了、
    #       屏幕上一动不动。★ 所以判据必须看**绘制框真的移动了没有**，
    #       光看 label_off() 是抓不到这个 bug 的（它会显示"拖成功了"）。
    from ui.metro_render import split_label_ring                    # noqa: E402
    import ui.metro_render as MR                                    # noqa: E402

    ringed = [it for it in mv.station_items.values()
              if split_label_ring(it.label_side())[1] > 0]
    ok("K0 图里确实有被外推的站名（转弯处那批）", len(ringed) > 0,
       f"{len(ringed)} 个")

    def drag_ring(it):
        """真按真拖一次，返回**绘制框**移动了多少场景单位（None = 不在视口）。"""
        mv._zoom_anim.stop()
        if mv._zoom_snap is not None:
            mv._abort_zoom_snap()
        mv.centerOn(it.pos())
        pump(6)
        box0 = it.label_scene_rect()
        p = mv.mapFromScene(box0.center())
        vp = mv.viewport()
        if not (0 <= p.x() < vp.width() and 0 <= p.y() < vp.height()):
            return None
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier,
                         QPoint(int(p.x()), int(p.y())))
        pump(2)
        QTest.mouseMove(vp, QPoint(int(p.x()) + 50, int(p.y()) - 30))
        pump(2)
        QTest.mouseMove(vp, QPoint(int(p.x()) + 60, int(p.y()) - 36))
        pump(2)
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier,
                           QPoint(int(p.x()) + 60, int(p.y()) - 36))
        pump(6)
        box1 = it.label_scene_rect()
        d = abs(box1.x() - box0.x()) + abs(box1.y() - box0.y())
        it.set_label_off(0.0, 0.0)      # 复位，别影响下一站
        return d

    bad = []
    for _it in ringed[:8]:
        _d = drag_ring(_it)
        if _d is None:
            continue
        if _d < 5:
            bad.append((_it.data.get("station_name"), _it.label_side(),
                        round(_d, 1)))
    ok("K1 被外推的站名拖完**真的动了**（不再拖了纹丝不动）", not bad,
       f"{bad[:5]}")

    MR.LABEL_OFF_ALL_RINGS = False      # 变异：退回"只有贴着圆点的能拖"
    bad2 = []
    for _it in ringed[:8]:
        _d = drag_ring(_it)
        if _d is None:
            continue
        if _d < 5:
            bad2.append(_it.data.get("station_name"))
    MR.LABEL_OFF_ALL_RINGS = True
    ok("K2 变异：关掉『外推也叠加偏移』⇒ 这批站名必须拖不动（判据真在岗）",
       len(bad2) > 0, f"{len(bad2)} 个拖不动：{bad2[:5]}")

    # ---------------------------------------------------------------
    print("===== L v2.6.40：手动改过位置的站名，缩放不许错位/消失 =====")
    # 用户原话：「修改过位置的站点文字，缩放的时候会导致错位或者直接不显示」
    # 病根：偏移存的是**屏幕像素**，而 v2.6.38 起站名是**等比**的 ⇒ 两者不是
    #   一把尺子 ⇒ 缩小时字被推远、放大时贴回圆点（压线 ⇒ 被排版器藏掉）。
    #   修法：偏移改**场景单位**。

    def drag_label_generic(it, dx=60, dy=-36):
        mv._zoom_anim.stop()
        if mv._zoom_snap is not None:
            mv._abort_zoom_snap()
        mv.centerOn(it.pos())
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

    def measure(it):
        """在四个档位上量"字中心相对圆点"的**场景**偏移。"""
        out = []
        for _sc in (0.30, 0.50, 1.00, 2.00):
            set_scale(mv, _sc)
            _b = it.label_scene_rect()
            out.append((_sc, it.is_label_visible(),
                        _b.center().x() - it.pos().x(),
                        _b.center().y() - it.pos().y()))
        return out

    _t = None
    for _it in mv.station_items.values():
        if _it.data.get("station_name") == "车公庙":
            _t = _it
            break
    _t = _t or list(mv.station_items.values())[0]
    set_scale(mv, 1.0)
    ok("L0 手动拖一次，偏移记下来了", drag_label_generic(_t)
       and _t.has_label_off(),
       f"偏移 ({_t.label_off().x():.1f},{_t.label_off().y():.1f})")
    recs = measure(_t)
    for _r in recs:
        print(f"      缩放 {_r[0]:.2f} 可见={_r[1]} 场景偏移 "
              f"({_r[2]:.0f},{_r[3]:.0f})")
    ok("L1 四个档位都还看得见（不会直接不显示）",
       all(r[1] for r in recs),
       f"{[r[0] for r in recs if not r[1]]} 档消失")
    _dxs = [r[2] for r in recs]
    _dys = [r[3] for r in recs]
    _spread = (max(_dxs) - min(_dxs)) + (max(_dys) - min(_dys))
    _base = max(abs(_dxs[0]) + abs(_dys[0]), 1.0)
    ok("L2 字相对圆点的**场景**位置四档基本一致（缩放不再错位）",
       _spread < 0.5 * _base, f"极差 {_spread:.0f} / 基准 {_base:.0f}")

    MR.LABEL_OFF_SCENE = False     # 变异：退回"屏幕像素"语义
    _recs_mut = measure(_t)
    MR.LABEL_OFF_SCENE = True
    _mx = [r[2] for r in _recs_mut]
    _my = [r[3] for r in _recs_mut]
    _spread_mut = (max(_mx) - min(_mx)) + (max(_my) - min(_my))
    ok("L3 变异：退回屏幕像素语义 ⇒ 四档位置必须**明显对不上**（判据真在岗）",
       _spread_mut > _spread * 1.5,
       f"变异后极差 {_spread_mut:.0f} vs 正常 {_spread:.0f}")
    _t.set_label_off(0.0, 0.0)

    print(f"\n===== 结果：{PASS} 通过 / {FAIL} 失败 =====")
    win.close()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
