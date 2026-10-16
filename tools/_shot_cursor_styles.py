# -*- coding: utf-8 -*-
"""
tools/_shot_cursor_styles.py
============================
**光标风格候选对比图**（只出图，不决定）—— 把 8 种地图光标并排画出来，
每种给**静止态 / 拖动态**两格，让用户直接看图挑。

v2.6.13 第二轮：用户看了 v2.6.13 第一版（A 圆环+圆心）后说"不喜欢这个样子"，
⇒ 把 A 剔掉，往两个方向各铺几条路：
  · **更克制**（少画、画小）：E 极简圆点 / G 圆点+刻度 / I 圆角方框
  · **更有语义**（明确"可以拖"）：F 四向箭头 / H 开口环
  · 原来那批取景器风格的：B 同心双环 / C 对焦框 / D 准星圆环

★ 形状绘制**必须和真光标同源**（挑中后把绘制函数搬进 `ui/map_cursor.py`
  ::paint_shape，保证"只此一份"）。预览图自己另写一套画法的话，
  用户看到的就不是真光标（v2.6.12 第一版预览靠 `QPixmap.scaled()` 缩放
  带 dpr=2 的位图，缩完只剩残缺一段弧 —— 白画）。
★ 自带"图里真有内容"自检：数非底色像素（渲染失败画布原样返回 ⇒ 断言永真，
  项目方法论 §5.7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QPointF, QRectF                    # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter,       # noqa: E402
                           QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import QApplication                        # noqa: E402

import ui.map_cursor as MC                                        # noqa: E402

BOX = 32          # 光标的**逻辑**尺寸（与 map_cursor.BOX 一致）
CELL = 112        # 预览每格边长（放大 3.5 倍，看得清）
PAD_TOP = 40      # 顶部方案名留白
LBL = 22          # **每格**下方"静止 / 拖动中"标签的高度
BG = QColor("#F7F9FB")     # 地图底色

_LOGS = ROOT / "logs"

_HALO = QColor(255, 255, 255, 232)      # 压在彩色线路上靠它保证可见
_DARK = QColor(MC.RING_COLOR)
_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _ring(pen):
    p = QPen(pen)
    p.setCapStyle(Qt.RoundCap)
    return p


# ---------------------------------------------------------------- 候选形状
def style_dual_ring(p, shape):
    """B 同心双环：外细环 + 内细环 + 中心点（取景器感，比单环"精密"一点）。
    shape = (外环半径, 线宽, 中心点半径)
    """
    outer_r, w, core_r = shape
    inner_r = outer_r * 0.5
    # ① 白描边
    pen = QPen(_HALO, w + 2 * MC.HALO_W)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(0, 0), outer_r, outer_r)
    p.drawEllipse(QPointF(0, 0), inner_r, inner_r)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(_HALO))
    p.drawEllipse(QPointF(0, 0), core_r + MC.HALO_W, core_r + MC.HALO_W)
    # ② 深色本体
    pen = QPen(_DARK, w)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(0, 0), outer_r, outer_r)
    p.drawEllipse(QPointF(0, 0), inner_r, inner_r)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(_DARK))
    p.drawEllipse(QPointF(0, 0), core_r, core_r)


def style_focus_frame(p, shape):
    """C 对焦框：四角括号 + 中心点（相机取景器 / 现代工具类）。
    shape = (半边长, 臂长, 中心点半径)
    """
    half, arm, core_r = shape
    lw = 2.0

    def corners(pen):
        p.setPen(pen)
        for sx in (-1, 1):
            for sy in (-1, 1):
                x, y = sx * half, sy * half
                p.drawLine(QPointF(x - sx * arm, y), QPointF(x, y))
                p.drawLine(QPointF(x, y), QPointF(x, y - sy * arm))

    pen = QPen(_HALO, lw + 2 * MC.HALO_W)
    pen.setCapStyle(Qt.RoundCap)
    corners(pen)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(_HALO))
    p.drawEllipse(QPointF(0, 0), core_r + MC.HALO_W, core_r + MC.HALO_W)
    pen = QPen(_DARK, lw)
    pen.setCapStyle(Qt.RoundCap)
    corners(pen)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(_DARK))
    p.drawEllipse(QPointF(0, 0), core_r, core_r)


def style_crosshair(p, shape):
    """D 准星圆环：圆环 + 四向刻度（CAD / 精确感，明确"这是中心点"）。
    shape = (环半径, 线宽, 中心点半径)
    """
    ring_r, w, core_r = shape
    t0, t1 = ring_r + 2.0, ring_r + 5.0

    def ticks(pen):
        p.setPen(pen)
        for dx, dy in _DIRS:
            p.drawLine(QPointF(dx * t0, dy * t0),
                       QPointF(dx * t1, dy * t1))

    pen = QPen(_HALO, w + 2 * MC.HALO_W)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(0, 0), ring_r, ring_r)
    ticks(pen)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(_HALO))
    p.drawEllipse(QPointF(0, 0), core_r + MC.HALO_W, core_r + MC.HALO_W)
    pen = QPen(_DARK, w)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(0, 0), ring_r, ring_r)
    ticks(pen)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(_DARK))
    p.drawEllipse(QPointF(0, 0), core_r, core_r)


def style_dot(p, shape):
    """E 极简圆点：**当前生效方案** —— 最小最克制，就是一个小实心圆 + 白描边
    （Figma 的 pointer 就是这个思路：不抢画面，只在需要时告诉你"点在哪"）。

    ★★ 这一格**直接调真光标函数** `MC.paint_shape`（而不是在这里抄一份画法）：
       用户看图挑中的就是这个，必须保证"预览看到的 == 装进 exe 的"
       —— 形状绘制只此一份（项目铁律，MEMORY §4.23③）。
    shape = (圆点半径, 外圈细环半径, 环线宽)
      静止：只有点（外环半径 0 = 不画）
      拖动：点**变小** + 外面浮出一圈细环 —— "捏住了"的收缩感
    """
    MC.paint_shape(p, shape)


def style_move_arrows(p, shape):
    """F 四向箭头（移动十字）：把"可以往四个方向拖"**直接画出来**，
    是最有语义的一个 —— 不用猜这个光标是干什么的。
    shape = (臂长, 线宽, 箭头长度)
    """
    arm, lw, ah = shape
    inner = arm * 0.30
    for color, extra in ((_HALO, 2 * MC.HALO_W), (_DARK, 0.0)):
        pen = QPen(color, lw + extra)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for dx, dy in _DIRS:
            ux, uy = -dy, dx                       # 垂直方向
            base = arm - ah
            p.drawLine(QPointF(dx * inner, dy * inner),
                       QPointF(dx * base, dy * base))
        p.setBrush(QBrush(color))
        for dx, dy in _DIRS:
            ux, uy = -dy, dx
            base = arm - ah
            tip = QPointF(dx * arm, dy * arm)
            b1 = QPointF(dx * base + ux * ah * 0.60, dy * base + uy * ah * 0.60)
            b2 = QPointF(dx * base - ux * ah * 0.60, dy * base - uy * ah * 0.60)
            p.drawPolygon(QPolygonF([tip, b1, b2]))
        p.setBrush(Qt.NoBrush)


def style_dot_ticks(p, shape):
    """G 圆点 + 四向刻度：中心一个小圆点，外面四个方向各一根短线
    —— 比纯圆点多一点"可移动"的暗示，又比四向箭头安静得多。
    shape = (圆点半径, 刻度起点, 刻度终点)
    """
    core_r, t0, t1 = shape
    for color, extra in ((_HALO, 2 * MC.HALO_W), (_DARK, 0.0)):
        pen = QPen(color, 1.8 + extra)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for dx, dy in _DIRS:
            p.drawLine(QPointF(dx * t0, dy * t0), QPointF(dx * t1, dy * t1))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        p.drawEllipse(QPointF(0, 0), core_r + (extra or MC.HALO_W),
                      core_r + (extra or MC.HALO_W))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(_DARK))
    p.drawEllipse(QPointF(0, 0), core_r, core_r)


def style_open_ring(p, shape):
    """H 开口环：一个**带缺口**的圆环（缺口开在正上方）
    —— 像"张开的抓手"，抽象但有机关感；比闭合圆环轻。
    shape = (半径, 线宽, 缺口角度)
    """
    r, w, gap = shape
    rect = QRectF(-r, -r, 2 * r, 2 * r)
    # ★ Qt 的 drawArc：角度单位是 **1/16 度**，0° = 3 点钟，**逆时针为正**
    #   ⇒ 12 点方向 = 90°。缺口居中在 90°，弧从 90+gap/2 转 360-gap。
    start = int(round((90 + gap / 2.0) * 16))
    span = int(round((360 - gap) * 16))
    for color, extra in ((_HALO, 2 * MC.HALO_W), (_DARK, 0.0)):
        pen = QPen(color, w + extra)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(rect, start, span)


def style_rounded_box(p, shape):
    """I 圆角方框：一个小的圆角矩形框（现代 UI 里"框选 / 抓手区域"的语汇）。
    shape = (半边长, 圆角半径, 线宽)
    """
    half, rad, lw = shape
    rect = QRectF(-half, -half, 2 * half, 2 * half)
    for color, extra in ((_HALO, 2 * MC.HALO_W), (_DARK, 0.0)):
        pen = QPen(color, lw + extra)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, rad, rad)


# (标题, 绘制函数, 静止态参数, 拖动态参数)
STYLES = [
    ("B 同心双环", style_dual_ring, (11.0, 1.4, 1.8), (8.5, 2.0, 2.8)),
    ("C 对焦框", style_focus_frame, (11.0, 5.5, 2.2), (8.0, 4.2, 3.2)),
    ("D 准星圆环", style_crosshair, (8.0, 1.8, 2.0), (6.0, 2.2, 3.2)),
    ("E 极简圆点（当前）", style_dot, MC.OPEN, MC.DRAG),
    ("F 四向箭头", style_move_arrows, (11.0, 2.0, 4.0), (8.5, 2.6, 3.4)),
    ("G 圆点+刻度", style_dot_ticks, (3.2, 5.5, 9.0), (4.2, 5.0, 7.5)),
    ("H 开口环", style_open_ring, (9.0, 2.2, 70.0), (6.5, 3.0, 40.0)),
    ("I 圆角方框", style_rounded_box, (9.0, 3.0, 2.0), (6.5, 2.5, 2.8)),
]


def main() -> int:
    app = QApplication(sys.argv)
    n = len(STYLES)
    W = CELL * n
    ROW = CELL + LBL                      # 每行 = 格子 + 下方标签
    H = PAD_TOP + ROW * 2
    pm = QPixmap(W, H)
    pm.fill(BG)                           # 用地图底色，才能看出白描边的效果
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setFont(QFont("Microsoft YaHei", 9))

    for i, (title, fn, s_open, s_drag) in enumerate(STYLES):
        x0 = i * CELL
        p.setPen(QColor("#111827"))
        p.drawText(QRectF(x0, 4, CELL, PAD_TOP - 10),
                   Qt.AlignHCenter | Qt.AlignVCenter, title)
        if i:
            p.setPen(QPen(QColor("#E3E8EF"), 1))
            p.drawLine(QPointF(x0, 6), QPointF(x0, H - 6))
        for j, (shape, tag) in enumerate(((s_open, "静止"), (s_drag, "拖动中"))):
            top = PAD_TOP + ROW * j
            cx, cy = x0 + CELL / 2.0, top + CELL / 2.0
            # 第一行垫一条红色"线路"：检验白描边压在彩色上还看不看得清
            if j == 0:
                p.setPen(QPen(QColor("#E53935"), 6))
                p.drawLine(QPointF(x0 + 12, cy), QPointF(x0 + CELL - 12, cy))
            p.save()
            p.translate(cx, cy)
            p.scale(CELL / float(BOX), CELL / float(BOX))
            fn(p, shape)
            p.restore()
            p.setPen(QColor("#6B7280"))
            p.drawText(QRectF(x0, top + CELL, CELL, LBL),
                       Qt.AlignHCenter | Qt.AlignVCenter, tag)
    p.end()

    _LOGS.mkdir(exist_ok=True)
    out = _LOGS / "_cursor_styles.png"
    pm.save(str(out))

    # ★ 自检：图里真有内容吗？（渲染失败画布原样返回 ⇒ 数出来只有 1 种颜色）
    img = pm.toImage()
    kinds = set()
    ink = 0
    for gx in range(0, img.width(), 4):
        for gy in range(0, img.height(), 4):
            c = img.pixelColor(gx, gy)
            kinds.add((c.red(), c.green(), c.blue()))
            if abs(c.red() - BG.red()) > 12 or abs(c.green() - BG.green()) > 12 \
                    or abs(c.blue() - BG.blue()) > 12:
                ink += 1
    print("[OK] %s  %dx%d" % (out, W, H))
    print("     方案：%s" % " / ".join(t for t, *_ in STYLES))
    print("     [自检] 颜色种数 %d，非底色取样点 %d %s"
          % (len(kinds), ink, "✅ 图里真有内容" if len(kinds) >= 4 and ink > 200
             else "❌ 疑似空白，预览白画了"))
    return 0 if (len(kinds) >= 4 and ink > 200) else 1


if __name__ == "__main__":
    raise SystemExit(main())
