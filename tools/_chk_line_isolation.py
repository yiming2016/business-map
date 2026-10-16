# -*- coding: utf-8 -*-
"""
_chk_line_isolation.py —— 回归：「双击图例只显示该线路」+ 右下角车厢编组卡片。

功能（v2.6.0）：
  双击左侧图例的一行 → 地图上只显示这一条线路（其它线路、以及不在这条线上的
  站点全部隐藏）；右下角浮出该线路的车厢编组（强冷/弱冷/商务车厢）。
  再双击一次 / 按 Esc / 点**地图右上角的红色大 ✕** → 恢复全图。
  （v2.6.4：原来那张红色 ✕ 是**右下角卡片上的一行蓝字**「✕ 显示全部」，
    用户嫌太不显眼，已删掉并挪到右上角。）

★★ 这条回归里最要紧的一条是 **B 组**：
    缩放动画的收尾 `_end_zoom_snap()` 原本是**无条件**把所有站点
    `setVisible(True)`（因为动画期间站点被整体藏起来、由 sprite 层代画）。
    若隔离状态只靠"图元可见性"表达，用户滚一下滚轮，被藏掉的几百个站
    就会全部冒出来。现在隔离是一个**逻辑开关**，收尾时要问它。
    `--mutate-old-zoom` 会把收尾还原成旧的无条件写法，B2 应当失败 ——
    用来证明这条回归真的抓得住。

判据：
  A 隔离：只有目标线路可见、只有该线路的站点可见、卡片出现且贴右下角、
          图例该行进入选中态
  B 缩放后隔离仍然成立（含动画开始/收尾两个阶段）
  C 三种退出方式都能恢复全图（再双击 / Esc / 卡片按钮）
  D 编组数据与三张官方截图一致（1-9,12,16 六节；10,13,14,20 八节；11 八节含商务）
  E 20 条线路逐个过一遍，卡片显隐都对
  F ★ 改窗口尺寸后卡片仍然贴在右下角（不许漂）
  G ★★ 卡片必须"融入背景"、不能是个"模块"（渲染到地图底色画布上，
       外圈 MARGIN 那一整圈像素必须**等于地图底色**；有边框/阴影/白底就会露馅）

运行：
    python tools/_chk_line_isolation.py
    python tools/_chk_line_isolation.py --mutate-old-zoom      # 应当失败（B 组）
    python tools/_chk_line_isolation.py --mutate-old-chrome    # 应当失败（F 组）
    python tools/_chk_line_isolation.py --mutate-panel-look    # 应当失败（G 组）
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

import core.data_manager as DM
from ui.main_window import MainWindow
from core.train_consist import BIZ, STRONG, WEAK, consist_for, legend_items

PASS = FAIL = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK]   %s   %s" % (name, detail))
    else:
        FAIL += 1
        print("  [FAIL] %s   %s" % (name, detail))


def mutate_old_chrome(mv) -> None:
    """把浮层位置还原成旧写法：只在状态变化时手动 move 一次（不每次绘制校正）。

    旧写法读到的 viewport().width() 是**上一帧**的值 → 连续 resize 时位置会漂。
    F1 应当失败，用来证明这条回归抓得住。

    ★★ 注意：映射表里的 `paintEvent` **必须挂在实例上**。
      PySide6 里给**类**换 `paintEvent` 是**完全不生效**的
      （实测：类上换 → render/update 都不会走到新方法，0 次调用；
      实例上换 → 正常走到）。所以下面用 `mv.paintEvent = …`。
      我第一版写成 `MapView.paintEvent = old_paint` —— 那行是死代码，
      幸好 F1 变红靠的是下面的 `layout_once`，否则这条回归会变成"假红"。
    """
    from PySide6.QtWidgets import QGraphicsView
    import types

    def old_paint(self, event):
        return QGraphicsView.paintEvent(self, event)     # 不做位置校正

    mv.paintEvent = types.MethodType(old_paint, mv)

    # 位置只在"隔离状态变化"时摆一次（模拟旧行为）
    _old_layout = type(mv)._layout_chrome          # 用未绑定的原函数
    _done = {"v": False}

    def layout_once(self):
        if not _done["v"]:
            _old_layout(self)
            _done["v"] = True
    mv._layout_chrome = types.MethodType(layout_once, mv)


def mutate_old_zoom() -> None:
    """把缩放收尾还原成旧写法：无条件 setVisible(True)（不尊重隔离状态）。"""
    def old_restore(self):
        for it in self.station_items.values():
            it.setVisible(True)

    from ui.map_view import MapView
    MapView._restore_station_visibility = old_restore


def mutate_panel_look(card) -> None:
    """把卡片还原成"独立模块"的老样子：不透明白底 + 描边。

    G 组要的就是"认得出模块感" —— 这一改，G1/G2 必须失败。
    ★ 同样必须挂在**实例**上（类上换 paintEvent 不生效，见 mutate_old_chrome）。
    """
    import types
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QBrush, QColor, QPainter, QPen

    orig = type(card).paintEvent

    def panel_paint(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(QColor("#E2E8F0"), 1))
        p.setBrush(QBrush(QColor(255, 255, 255, 240)))     # 不透明白底
        p.drawRoundedRect(QRectF(0.5, 0.5, self._w - 1.0, self._h - 1.0),
                          12, 12)
        p.end()
        orig(self, ev)

    card.paintEvent = types.MethodType(panel_paint, card)


# ----------------------------------------------------------------------
# G 组用：把卡片渲染到指定底色的画布上，返回 (QImage, dpr)
# ----------------------------------------------------------------------
def _render_card_on(card, bg_hex: str):
    """把卡片单独渲染到指定底色的画布上。

    ★ 必须显式指定 `DrawChildren`（不带 `DrawWindowBackground`）：
      `render()` 的默认 flags 含 DrawWindowBackground，会把 widget 的
      **调色板窗口底色（#F3F3F3）** 整块刷上去 —— 那是"测试自己画上去的"，
      不是真实运行时的样子（真实运行时父控件先画、子控件不填底）。
      第一版没加这个 flag，G1/G2 报的"外圈是 #f3f3f3"就是它，
      差点让我去改一个根本不存在的 bug。
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QImage, QRegion
    from PySide6.QtWidgets import QWidget
    dpr = float(card.devicePixelRatioF()) or 1.0
    W = int(round(card.width() * dpr))
    H = int(round(card.height() * dpr))
    img = QImage(W, H, QImage.Format_RGB32)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(bg_hex))
    card.render(img, QPoint(0, 0), QRegion(),
                QWidget.RenderFlags(QWidget.DrawChildren))
    return img, dpr


def _png(img, dpr: float, lx: int, ly: int):
    """逻辑坐标 → 像素颜色。"""
    from PySide6.QtGui import QColor
    x = min(img.width() - 1, max(0, int(lx * dpr)))
    y = min(img.height() - 1, max(0, int(ly * dpr)))
    return QColor(img.pixel(x, y))


def dblclick_row(row) -> None:
    """真的走一次 mouseDoubleClickEvent（不只是发信号）。"""
    try:
        ev = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(6, 6),
                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        row.mouseDoubleClickEvent(ev)
    except Exception as e:                      # 签名差异时退化为发信号
        print("     （构造双击事件失败，改用直接发信号：%s）" % e)
        row.double_clicked.emit(row.line_id)


def visible_line_ids(mv):
    return sorted(lid for lid, it in mv.line_items.items() if it.isVisible())


def visible_station_ids(mv):
    return sorted(sid for sid, it in mv.station_items.items() if it.isVisible())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate-old-zoom", action="store_true")
    ap.add_argument("--mutate-old-chrome", action="store_true")
    ap.add_argument("--mutate-panel-look", action="store_true")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    app.processEvents()

    tmp = Path(tempfile.mkdtemp(prefix="chk_isolation_"))
    DM.STATIONS_FILE = tmp / "stations.json"
    DM.LINES_FILE = tmp / "lines.json"

    if args.mutate_old_zoom:
        mutate_old_zoom()
    if args.mutate_old_chrome:
        mutate_old_chrome(win.map_view)
    if args.mutate_panel_look:
        mutate_panel_look(win.consist_card)

    mv = win.map_view
    all_lines = sorted(mv.line_items.keys())
    all_stations = sorted(mv.station_items.keys())

    print("=" * 78)
    print("视口 %dx%d   线路 %d   站点 %d%s"
          % (mv.viewport().width(), mv.viewport().height(),
             len(all_lines), len(all_stations),
             "   【变异：缩放收尾回到无条件 setVisible(True)】"
             if args.mutate_old_zoom else ""))
    print("落盘目标已改到临时目录：%s" % tmp)

    # ==================================================================
    print("\nA 组：双击图例 → 只显示这条线路")
    # ==================================================================
    target = "11" if "11" in all_lines else all_lines[0]
    row = next((r for r in win.legend_panel._rows if r.line_id == target), None)
    ok("A0 找得到图例里这一行", row is not None, target)

    dblclick_row(row)
    app.processEvents()

    ok("A1 线路只剩这一条", visible_line_ids(mv) == [target],
       "可见线路 %s" % visible_line_ids(mv))

    allow = {sid for sid, st in win.dm.all_stations().items()
             if target in (st.get("lines") or [])}
    vis = set(visible_station_ids(mv))
    ok("A2 站点只剩这条线上的", vis == allow,
       "可见 %d 个 / 该线路 %d 个（全部 %d）" % (len(vis), len(allow), len(all_stations)))
    ok("A3 确实少了一大批（不是全都显示）", len(vis) < len(all_stations),
       "%d → %d" % (len(all_stations), len(vis)))
    ok("A4 map_view.isolated_line() 记着它", mv.isolated_line() == target,
       mv.isolated_line())

    card = win.consist_card
    close_btn = win.isolated_close
    ok("A5 车厢编组卡片出现了", card.isVisible(), "")
    vp = mv.viewport()
    if card.isVisible():
        # ★ 判"贴右下角"要看**右边缘/下边缘**离视口边多远 ——
        #   不能要求"左边缘过中线"：卡片本身宽 495px，在 874 宽的视口里
        #   左边缘必然在中线左边（这是对的，不是错位）。
        M = 16
        rgap = vp.width() - (card.x() + card.width())
        bgap = vp.height() - (card.y() + card.height())
        in_br = (0 <= rgap <= M and 0 <= bgap <= M
                 and card.x() >= 0 and card.y() >= 0)
        ok("A6 卡片贴在地图右下角（右/下边距 ≤%dpx）" % M, in_br,
           "card=(%d,%d %dx%d) 视口=%dx%d 右边距=%d 下边距=%d"
           % (card.x(), card.y(), card.width(), card.height(),
              vp.width(), vp.height(), rgap, bgap))
        ok("A7 卡片线路名对得上",
           card.line_name() == win.dm.get_line(target).get("name"),
           card.line_name())

    ok("A8 图例该行进入选中态", row._isolated is True, str(row._isolated))

    # ---- A9/A10 数据重建（保存、导入、图例刷新都会走这条路）之后隔离要还在 ----
    #      ★ 图元是新建的，隔离必须能重新贴上去，否则"一保存就悄悄失效"。
    win.map_view.reload_stations(win.dm.all_stations())
    win.map_view.rebuild_lines()
    win.legend_panel.set_lines(win.dm.all_lines(), win.dm.all_stations())
    app.processEvents()
    ok("A9 数据重建（保存/导入路径）后隔离仍在",
       set(visible_station_ids(mv)) == allow
       and visible_line_ids(mv) == [target],
       "站点 %d/%d 线路 %s" % (len(visible_station_ids(mv)),
                               len(allow), visible_line_ids(mv)))
    ok("A10 图例重建后选中态也贴回来了",
       any(r.line_id == target and r._isolated
           for r in win.legend_panel._rows), "")

    # ==================================================================
    print("\nB 组：★ 缩放之后隔离必须仍然成立")
    # ==================================================================
    mv._begin_zoom_snap()
    app.processEvents()
    ok("B1 动画期间站点整体隐藏（这是原本的设计，不是 bug）",
       len(visible_station_ids(mv)) == 0,
       "可见 %d 个" % len(visible_station_ids(mv)))

    mv._end_zoom_snap(repaint_now=False, reveal=False)
    app.processEvents()
    after = set(visible_station_ids(mv))
    ok("B2 ★ 收尾后仍然只有这条线的站（没把别的站放出来）", after == allow,
       "可见 %d 个 / 该线路 %d 个" % (len(after), len(allow)))
    ok("B3 收尾后线路仍然只剩这一条", visible_line_ids(mv) == [target],
       "可见线路 %s" % visible_line_ids(mv))
    ok("B4 卡片还在（没被缩放快照蒙住）", card.isVisible(), "")

    # ==================================================================
    print("\nC 组：三种退出方式")
    # ==================================================================
    dblclick_row(row)
    app.processEvents()
    ok("C1 再双击同一行 → 恢复全图",
       len(visible_station_ids(mv)) == len(all_stations)
       and len(visible_line_ids(mv)) == len(all_lines)
       and not card.isVisible(),
       "站点 %d/%d 线路 %d/%d 卡片可见=%s"
       % (len(visible_station_ids(mv)), len(all_stations),
          len(visible_line_ids(mv)), len(all_lines), card.isVisible()))

    win._on_legend_double_clicked(target)
    app.processEvents()
    ok("C2 先进入隔离（为测 Esc）", mv.isolated_line() == target, "")
    mv.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    app.processEvents()
    ok("C2 Esc → 退出单独显示",
       mv.isolated_line() == "" and not card.isVisible(), "")

    win._on_legend_double_clicked(target)
    app.processEvents()
    # v2.6.4：退出入口 = 右上角红色大 ✕（不再是卡片上那行「✕ 显示全部」）
    ok("C3a 右上角红色 ✕ 出现", close_btn.isVisible(),
       "可见=%s geom=%s" % (close_btn.isVisible(),
                            close_btn.geometry().getRect()))
    ok("C3b 卡片上已无「✕ 显示全部」这种东西（卡片不响应点击）",
       not hasattr(card, "_btn_rect")
       and not hasattr(card, "close_requested"),
       "卡片属性 _btn_rect=%s close_requested=%s"
       % (hasattr(card, "_btn_rect"), hasattr(card, "close_requested")))
    close_btn.clicked.emit()
    app.processEvents()
    ok("C3c 点右上角 ✕ → 退出",
       mv.isolated_line() == "" and not card.isVisible()
       and not close_btn.isVisible()
       and len(visible_station_ids(mv)) == len(all_stations),
       "站点 %d/%d 卡片=%s ✕=%s"
       % (len(visible_station_ids(mv)), len(all_stations),
          card.isVisible(), close_btn.isVisible()))

    ok("C4 退出后图例选中态清掉了",
       all(not r._isolated for r in win.legend_panel._rows), "")

    # ==================================================================
    print("\nF 组：★ 改窗口大小之后，卡片必须仍然贴在右下角（不许漂）")
    # ==================================================================
    #   ★★ 这条守的是一个"只有改窗口大小才暴露"的 bug：
    #     原来 `_reposition_consist_card()` 手动 move，读到的
    #     viewport().width() 是**上一帧**的值 —— 连续改窗口大小时位置一帧一帧漂，
    #     实测 1600x1000 时右边距漂到 **-284**（整块跑到视口右边界外面），
    #     1280x800 时 x 从 163 漂到 63。用户看到的就是"没固定在右下角"。
    #     现在位置由 MapView.paintEvent → _layout_chrome 用**当前**尺寸统一校正。
    win._on_legend_double_clicked(target)
    app.processEvents()
    ok("F0 重新进入隔离（为测 resize）", card.isVisible(), "")

    M = 16
    bad = []
    for w, h in [(1000, 700), (1600, 1000), (1920, 1080), (1280, 800), (1480, 900)]:
        win.resize(w, h)
        app.processEvents()
        app.processEvents()          # ★ 多转一圈：漂移位 bug 恰恰是"下一帧才错"
        vp = mv.viewport()
        rgap = vp.width() - (card.x() + card.width())
        bgap = vp.height() - (card.y() + card.height())
        if not (0 <= rgap <= M and 0 <= bgap <= M):
            bad.append("%dx%d 右边距%d 下边距%d" % (w, h, rgap, bgap))
    ok("F1 五种窗口尺寸下边距都 ≤%dpx" % M, not bad,
       ("；".join(bad) if bad else "1000x700 / 1600x1000 / 1920x1080 / 1280x800 / 1480x900 全对"))

    # 窄视口：卡片必须自己缩窄，不能比地图还宽（原来固定 495px，视口 394 就爆了）
    win.resize(1000, 700)
    app.processEvents(); app.processEvents()
    vp = mv.viewport()
    ok("F2 窄视口下卡片宽度不超过可用宽度",
       card.width() <= vp.width() - 2 * M,
       "卡片 %d ≤ 可用 %d（视口 %d）" % (card.width(), vp.width() - 2 * M, vp.width()))
    ok("F3 车厢行仍能画出来（缩放下限内）",
       card._car_scale >= 0.55 and len(card._cars) == 8,
       "缩放 %.2f，车厢 %d 节" % (card._car_scale, len(card._cars)))
    win.resize(1480, 900)
    app.processEvents()

    # ==================================================================
    print("\nD 组：编组数据与官方截图一致")
    # ==================================================================
    six = [str(i) for i in range(1, 10)] + ["12", "16"]
    eight = ["10", "13", "14", "20"]
    ok("D1 1~9/12/16 = 六节（1弱 2-5强 6弱）",
       all(consist_for(k) == WEAK + STRONG * 4 + WEAK for k in six),
       str({k: consist_for(k) for k in six}))
    ok("D2 10/13/14/20 = 八节（1弱 2-7强 8弱）",
       all(consist_for(k) == WEAK + STRONG * 6 + WEAK for k in eight),
       str({k: consist_for(k) for k in eight}))
    ok("D3 11号线 = 八节且 7/8 为商务车厢（只画一个列车图标）",
       consist_for("11") == WEAK + STRONG * 4 + WEAK + BIZ * 2,
       str(consist_for("11")))

    lg = legend_items(consist_for("1"))
    ok("D4 六节图例文字 = ['1/6节为弱冷车厢','2-5节为强冷车厢']",
       [x[2] for x in lg] == ["1/6节为弱冷车厢", "2-5节为强冷车厢"],
       str([x[2] for x in lg]))
    lg8 = legend_items(consist_for("10"))
    ok("D5 八节图例文字 = ['1/8节为弱冷车厢','2-7节为强冷车厢']",
       [x[2] for x in lg8] == ["1/8节为弱冷车厢", "2-7节为强冷车厢"],
       str([x[2] for x in lg8]))
    lg11 = legend_items(consist_for("11"))
    ok("D6 11号线图例三条，末条 = '7/8节车厢为商务车厢'",
       [x[2] for x in lg11] == ["1/6节为弱冷车厢", "2-5节为强冷车厢",
                                "7/8节车厢为商务车厢"],
       str([x[2] for x in lg11]))

    # ==================================================================
    print("\nE 组：20 条线路逐个过一遍")
    # ==================================================================
    bad = []
    for r in win.legend_panel._rows:
        lid = r.line_id
        win._on_legend_double_clicked(lid)
        app.processEvents()
        if consist_for(lid) is not None and not card.isVisible():
            bad.append("%s(有资料却没出卡片)" % lid)
        if consist_for(lid) is None and not card.isVisible():
            bad.append("%s(无资料却没出卡片)" % lid)
        win._exit_isolation()
        app.processEvents()
    ok("E1 20 条线路逐个试过，卡片显隐都对", not bad, str(bad) or "全部正常")

    no_data = [lid for lid in all_lines if consist_for(lid) is None]
    print("     没有编组资料的线路（卡片写「暂无资料」）：%s" % no_data)

    # ==================================================================
    print("\nG 组：★ 卡片必须「融入背景」，不能像个独立模块")
    # ==================================================================
    #  判据说明：地图底色是固定的 #F7F9FB。把卡片渲染到**同色画布**上，
    #  卡片内边距（MARGIN=14）那一整圈是**不画任何内容的空白**，
    #  所以它的像素必须原封不动等于地图底色。
    #     · 有一圈描边      → 外圈某个像素变成边框色 → 失败
    #     · 有阴影          → 外圈变暗             → 失败
    #     · 底色用纯白/不透 → 外圈整片比底色亮     → 失败
    #  换句话说：**"看起来像个模块"这件事，在这一圈像素上一定会留下证据。**
    from PySide6.QtCore import QPoint, QRectF
    from PySide6.QtGui import QBrush, QColor, QPainter, QPen
    from ui.train_consist_card import CARD_BG, MARGIN, SHADOW_PAD

    if next((r for r in win.legend_panel._rows if r.line_id == "3"), None):
        win._on_legend_double_clicked("3")
        app.processEvents()

    BG = QColor(CARD_BG)
    CANVAS = "#F7F9FB"
    ok("G0 画布底色 == 地图底色 == 卡片底色常量（否则整组无意义）",
       QColor(CANVAS) == BG,
       "地图/画布 %s  卡片常量 %s" % (CANVAS, CARD_BG))

    def band_worst(img, dpr):
        """外圈空白带里，与地图底色差得最远的一个像素。"""
        out = SHADOW_PAD + 1                 # 最外 3px 本来就不画，跳过
        inn = SHADOW_PAD + MARGIN - 2        # 进内容区之前收手
        w, h = card.width(), card.height()
        worst, at = -1, None
        for ly in range(out, h - out):
            for lx in range(out, w - out):
                if inn <= lx < w - inn and inn <= ly < h - inn:
                    continue                 # 跳过内容区，只看空白外圈
                c = _png(img, dpr, lx, ly)
                d = max(abs(c.red() - BG.red()), abs(c.green() - BG.green()),
                        abs(c.blue() - BG.blue()))
                if d > worst:
                    worst, at = d, (lx, ly, c.name())
        return worst, at

    img, dpr = _render_card_on(card, CANVAS)

    # ---- G0b 自检：卡片**真的画上了东西** ----
    #  ★★ 这条不能省：渲染若失败（画布原样返回），外圈当然等于底色 ——
    #     那样 G1 会"永远通过"。一个从不报错的校验器等于没有。
    painted = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = QColor(img.pixel(x, y))
            if abs(c.red() - BG.red()) + abs(c.green() - BG.green()) \
                    + abs(c.blue() - BG.blue()) > 24:
                painted += 1
    ok("G0b 渲染自检：卡片确实画出了内容（不是一张空白画布）",
       painted > 500, "非底色像素采样 %d 个（应远大于 500）" % painted)

    # ---- G1：外圈空白带必须完全是地图底色 ----
    worst, at = band_worst(img, dpr)
    ok("G1 外圈空白带 == 地图底色（无描边 / 无阴影 / 非白底）",
       worst <= 2, "最大偏差 %d（阈值 2）  最差点 %s" % (worst, at))

    # ---- G2：组件最外 SHADOW_PAD 几 px 也不能画东西 ----
    #  （否则就是一个硬边矩形，比如谁给 widget 设了 autoFillBackground）
    img_red, dpr_red = _render_card_on(card, "#E60012")   # 饱和红，最容易露馅
    worst2, at2 = -1, None
    for ly in range(0, SHADOW_PAD):
        for lx in range(0, card.width()):
            c = _png(img_red, dpr_red, lx, ly)
            d = max(abs(c.red() - 0xE6), abs(c.green() - 0x00),
                    abs(c.blue() - 0x12))
            if d > worst2:
                worst2, at2 = d, (lx, ly, c.name())
    ok("G2 组件最外 SHADOW_PAD 像素完全没画（否则成硬边矩形）",
       worst2 <= 2, "最大偏差 %d  最差点 %s" % (worst2, at2))

    # ---- G3：底色必须"能挡住线路"（不是全透明）----
    #  全透明的话线路会直接穿过文字，同样没法看。
    inside = _png(img_red, dpr_red, SHADOW_PAD + MARGIN // 2,
                  SHADOW_PAD + MARGIN // 2)
    dist = abs(inside.red() - 0xE6) + abs(inside.green() - 0x00) \
        + abs(inside.blue() - 0x12)
    ok("G3 空白带能挡住底下的线路（底色不是全透明）",
       dist > 40, "在被遮住的饱和红上呈现 %s（与红距离 %d，需 >40）"
                  % (inside.name(), dist))

    # ---- G4：★ 变异自检 —— 把卡片换回"白底 + 描边"的老样子，G1 必须报错 ----
    #  这一条证明 G1 不是"永远通过"的假测试。
    _saved_paint = card.paintEvent
    try:
        mutate_panel_look(card)
        img_m, dpr_m = _render_card_on(card, CANVAS)
        worst_m, at_m = band_worst(img_m, dpr_m)
    finally:
        card.paintEvent = _saved_paint
    ok("G4 变异自检：换回「白底+描边」时 G1 确实会报错",
       worst_m > 2, "老样子下最大偏差 %d（应 >2）  最差点 %s" % (worst_m, at_m))

    # ---- G5：★★ 地面真值 —— 从**真实窗口画面**里量（不靠上面那套合成渲染）----
    #  取「卡片空白带」的一点，与「卡片正上方 40px 的地图」比色。
    #  这一条同时兜住 G0b 的漏洞：万一 render 的参数写错、画布原样返回，
    #  合成测试会假通过，但真实画面比色不会。
    img_w = win.grab().toImage()
    dpr_w = float(win.devicePixelRatioF()) or 1.0
    tl = card.mapTo(win, QPoint(0, 0))
    px_a = tl.x() + SHADOW_PAD + MARGIN // 2
    py_a = tl.y() + SHADOW_PAD + MARGIN // 2
    A = _png(img_w, dpr_w, int(px_a), int(py_a))

    def _patch_uniform(cx, cy, half=8):
        """以 (cx,cy) 为心取 (2*half+1)² 逻辑像素，返回 (是否纯色, 平均色)。"""
        rs = gs = bs = 0
        n = 0
        c0 = None
        for dy in range(-half, half + 1):
            for dx in range(-half, half + 1):
                c = _png(img_w, dpr_w, int(cx + dx), int(cy + dy))
                if c0 is None:
                    c0 = c
                elif abs(c.red() - c0.red()) + abs(c.green() - c0.green()) \
                        + abs(c.blue() - c0.blue()) > 12:
                    return False, c
                rs += c.red(); gs += c.green(); bs += c.blue(); n += 1
        return True, QColor(rs // n, gs // n, bs // n)

    B, ref_ok, ref_y = None, False, 0
    for k in range(1, 9):                       # 往上找一块"干净的地图"当参照
        ref_y = int(py_a) - 30 * k
        u, c = _patch_uniform(px_a, ref_y)
        if u:
            B, ref_ok = c, True
            break
    if not ref_ok:
        ok("G5 真实画面：卡片空白带与旁边地图同色（不成形）", False,
           "在卡片上方 30~240px 内找不到一块干净地图当参照，无法判定")
    else:
        d5 = max(abs(A.red() - B.red()), abs(A.green() - B.green()),
                 abs(A.blue() - B.blue()))
        ok("G5 真实画面：卡片空白带与旁边地图同色（不成形）",
           d5 <= 2, "卡片内 %s  vs  上方 %dpx 处 %s   差 %d"
                    % (A.name(), int(py_a) - ref_y, B.name(), d5))

    win._exit_isolation()
    app.processEvents()

    # ==================================================================
    print("\nH 组：★ 退出入口必须是「右上角的红色大 ✕」（v2.6.4）")
    # ==================================================================
    #  用户原话：「双击对应线路右下方的 ❌ 显示全部，删掉，改为在右上角添加红色的大 ❌」。
    #  换成可量化的三条：**够大** / **贴右上角** / **够红（故意不融入背景）**。
    ok("H0 未隔离时 ✕ 是隐藏的", not close_btn.isVisible(),
       "可见=%s" % close_btn.isVisible())

    win._on_legend_double_clicked(target)
    app.processEvents()
    ok("H1 ✕ 够大（≥36px 见方；原来那行蓝字是 70×20，还是淡色的）",
       close_btn.width() >= 36 and close_btn.height() >= 36,
       "%dx%d" % (close_btn.width(), close_btn.height()))

    M2 = 16
    bad2 = []
    for w, h in [(1000, 700), (1600, 1000), (1920, 1080), (1280, 800), (1480, 900)]:
        win.resize(w, h)
        app.processEvents(); app.processEvents()
        vp = mv.viewport()
        rgap = vp.width() - (close_btn.x() + close_btn.width())
        tgap = close_btn.y()
        if not (0 <= rgap <= M2 and 0 <= tgap <= M2):
            bad2.append("%dx%d 右边距%d 上边距%d" % (w, h, rgap, tgap))
    ok("H2 五种窗口尺寸下都贴在**右上角**（右边距/上边距 ≤%dpx）" % M2, not bad2,
       ("；".join(bad2) if bad2 else
        "1000x700 / 1600x1000 / 1920x1080 / 1280x800 / 1480x900 全对"))
    win.resize(1480, 900)
    app.processEvents(); app.processEvents()

    # ---- 真的画成红的了吗：渲到画布上数像素 ----
    img_x, dpr_x = _render_card_on(close_btn, "#FFFFFF")
    cx = close_btn.width() / 2.0
    hx = int(round(close_btn.width() * 0.34))
    hy = close_btn.height() / 2.0
    core = _png(img_x, dpr_x, cx - cx + 3, hy)          # 靠左边缘内侧，避开白叉
    ok("H3 底色是**红**的（R 明显大于 G/B）",
       core.red() > 180 and core.red() - core.green() > 80
       and core.red() - core.blue() > 80,
       "内侧像素 = %s" % core.name())

    # 圆内必须能找到白色像素（那根 ✕），否则可能只是画了个红饼
    whites = 0
    for lx in range(2, close_btn.width() - 2):
        for ly in range(2, close_btn.height() - 2):
            c = _png(img_x, dpr_x, lx, ly)
            if c.red() > 235 and c.green() > 235 and c.blue() > 235:
                dx, dy = lx - cx, ly - hy
                if dx * dx + dy * dy < (close_btn.width() / 2.0 - 4) ** 2:
                    whites += 1
    ok("H4 红圆里真的画了白色的 ✕", whites >= 30,
       "圆内白色像素 %d 个（<30 就说明只画了个红饼）" % whites)

    # ---- ★ 与"融入背景"相反：故意要醒目 ----
    #  判据：和地图底色 #F7F9FB 的色差要**足够大**。
    #  （G 组要求卡片与底图色差 ≤2，这里要求 ≥80 —— 两条正好相反，是有意的：
    #    卡片是信息、要让开视线；✕ 是操作、要被一眼看到。）
    bgc = QColor("#F7F9FB")
    d_bg = max(abs(core.red() - bgc.red()), abs(core.green() - bgc.green()),
               abs(core.blue() - bgc.blue()))
    ok("H5 ✕ **故意不融入背景**：与地图底色色差 ≥80（醒目）",
       d_bg >= 80, "✕ %s vs 地图 %s  差 %d" % (core.name(), bgc.name(), d_bg))

    # ---- 变异自检：把颜色改成地图底色，H5 必须挂 ----
    #  没有这一条，"H5 通过"可能只是因为判据恒真（一个从不报错的校验器等于没有）。
    import ui.isolated_close_button as _icb
    _saved = (_icb.COLOR_BASE, _icb.COLOR_HOVER, _icb.COLOR_PRESS,
              _icb.RING_COLOR)
    try:
        _icb.COLOR_BASE = _icb.COLOR_HOVER = _icb.COLOR_PRESS = "#F7F9FB"
        _icb.RING_COLOR = "#F7F9FB"
        btn2 = _icb.IsolatedCloseButton()
        img_m, dpr_m = _render_card_on(btn2, "#FFFFFF")
        c_m = _png(img_m, dpr_m, 3, btn2.height() / 2.0)
        d_m = max(abs(c_m.red() - bgc.red()), abs(c_m.green() - bgc.green()),
                  abs(c_m.blue() - bgc.blue()))
    finally:
        (_icb.COLOR_BASE, _icb.COLOR_HOVER, _icb.COLOR_PRESS,
         _icb.RING_COLOR) = _saved
    ok("H6 变异自检：改成地图底色后色差骤降（说明 H5 判据真的在上岗）",
       d_m < 80, "变异后色差 %d（原判据要求 ≥80）" % d_m)

    win._exit_isolation()
    app.processEvents()
    ok("H7 退出后 ✕ 收起", not close_btn.isVisible(), "")

    print("\n" + "=" * 78)
    print("通过 %d 项，失败 %d 项" % (PASS, FAIL))
    print("结论：%s" % ("全部通过 ✅" if FAIL == 0 else "有失败 ❌"))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
