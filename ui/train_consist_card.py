# -*- coding: utf-8 -*-
"""
ui/train_consist_card.py
========================
右下角浮层：显示某条线路的**车厢编组**（强冷 / 弱冷 / 商务车厢）。

只在"单独显示某条线路"时出现（见 MapView.set_isolated_line）。

画法说明（为什么不直接贴图）：
    原图是位图，缩放会糊、深色主题也对不上；这里全部用 QPainter 矢量绘制，
    配色取自原图截图（见 core/train_consist.PALETTE），任意 DPI 都清晰。
    雪花/公文包两个图标也是**手画**的 —— 不依赖系统字体里有没有 ❄ / 💼 字形。

挂在 MapView.viewport() 下，所以它是地图上的"界面层"：
    · 缩放动画期间那层合成快照盖住的是地图，不会盖住它
    · 截图（PrintWindow）里也能拍到
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QWidget

from core.train_consist import (
    BIZ, CAR_NAME, PALETTE, WEAK, cars as consist_cars, legend_items,
)

# ---------------- 度量（逻辑像素）----------------
CAR_W = 54          # 单节车厢宽
CAR_H = 34          # 单节车厢高
CAR_GAP = 3         # 车厢间隙
CAR_R = 5           # 车厢圆角（头/尾车的"鼻子"端用 NOSE_R）
NOSE_R = 15         # 头车/尾车外端的圆角（做出车头轮廓）

BADGE_W = 30        # 节号小方牌宽
BADGE_H = 17
BADGE_GAP = 2       # 方牌与车身之间

MARGIN = 14         # 卡片内边距
TITLE_H = 22
GAP_TITLE = 9
GAP_LEGEND = 13
LEGEND_H = 19       # 每个图例行高
LEGEND_ICON = 13    # 图例前的小方块边长
LEGEND_GAP = 16     # 图例项之间

MIN_CONTENT_W = 220
# ★ 只是给圆角留的呼吸空间，**不再画外圈/阴影** ——
#   阴影是"浮起来的模块"最主要的观感来源，去掉它才会"沉进地图背景里"。
SHADOW_PAD = 3

# ★★ "融入背景"的最终解：底色直接用**地图自己的背景色**
#   地图视图的底色是固定的 #F7F9FB（见 MapView.__init__ 的 setBackgroundBrush）。
#   卡片只要也用这个颜色，它在地图上**根本不构成一个形状**；
#   唯一能看出它的地方，是它压在彩色线路上的那一小块（那是必须挡的，
#   否则线路+站名穿过文字会糊成一片）。
#   之前用纯白 #FFFFFF → 比底图亮一档 → 一眼就是个白方块。
CARD_BG = "#F7F9FB"
CARD_ALPHA = 235
# ★★ v2.6.4：原来这里是右上角「✕ 显示全部」按钮的宽高（BTN_W/BTN_H）。
#   用户要求把退出入口挪到**地图右上角的红色大 ✕**（ui/isolated_close_button.py），
#   卡片上那颗按钮整个删掉，这里不再需要常量。

# 车厢行的整体缩放下限（窄视口下按可用宽度缩，但不能缩到看不清）
CAR_SCALE_MIN = 0.55

FONT_FAMILY = "Microsoft YaHei"


class TrainConsistCard(QWidget):
    """车厢编组卡片。固定尺寸、自绘、默认隐藏。

    ★ v2.6.4：**纯展示**，不响应任何点击（原来右上角那颗「✕ 显示全部」已删除）。
      退出「只看这一条线」改走地图右上角的红色大 ✕。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TrainConsistCard")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.setCursor(Qt.ArrowCursor)

        self._line_name = ""
        self._line_color = "#888888"
        self._consist: Optional[str] = None
        self._cars: List[str] = []
        self._legend: List[Tuple[str, str, str]] = []
        self._legend_rows: List[List[Tuple[str, str, str]]] = []
        self._w = 260
        self._h = 130
        self._max_w = 10 ** 6      # 可用宽度上限（由 MapView._layout_chrome 下发）
        self._car_scale = 1.0      # 车厢行整体缩放（窄视口下按可用宽度缩）
        self.hide()

    # ------------------------------------------------------------ 内容
    def set_line(self, line_name: str, line_color: str,
                 consist: Optional[str]) -> None:
        self._line_name = line_name or ""
        self._line_color = line_color or "#888888"
        self._consist = consist
        self._cars = consist_cars(consist) if consist else []
        self._legend = legend_items(consist) if consist else []
        self._relayout()

    def line_name(self) -> str:
        return self._line_name

    # ------------------------------------------------------------ 尺寸
    def fit_to_width(self, max_w: int) -> None:
        """按视口给的宽度上限重排。

        ★ 为什么需要它：卡片原来是**固定宽度**（实测 495px）。
          窗口小到视口只有 394px 时，卡片比地图还宽 → `max(0, …)` 把 x 夹到 0，
          看起来就是"没贴在右下角、甚至被切掉一截"。
          现在宽度跟着视口走，车厢行按可用宽度整体缩放。
        """
        m = max(160, int(max_w))
        if m == self._max_w:
            return                      # 没变就别重排（省一次字体度量）
        self._max_w = m
        self._relayout()

    def _relayout(self) -> None:
        n = len(self._cars)
        car_w_full = n * CAR_W + (n - 1) * CAR_GAP if n else 0

        # 宽度要容得下标题（线路名长的时候，「有轨电车 · 车厢编组」不能被截）
        fm_title = QFontMetrics(QFont(FONT_FAMILY, 9, QFont.Bold))
        title_w = 30 + fm_title.horizontalAdvance("%s · 车厢编组" % self._line_name)
        want = max(car_w_full, MIN_CONTENT_W, title_w + 10)
        avail = max(160, self._max_w - MARGIN * 2 - SHADOW_PAD * 2)
        content_w = min(want, avail)

        # 车厢行放不下就整体缩放（保底 CAR_SCALE_MIN，再小就看不清了）
        self._car_scale = 1.0
        if n and car_w_full > content_w:
            self._car_scale = max(CAR_SCALE_MIN, content_w / car_w_full)
        car_w = car_w_full * self._car_scale

        # 图例按可用宽度换行
        fm = QFontMetrics(QFont(FONT_FAMILY, 8))
        rows: List[List[Tuple[str, str, str]]] = [[]]
        used = 0.0
        for it in self._legend:
            w = LEGEND_ICON + 5 + fm.horizontalAdvance(it[2])
            if rows[-1] and used + LEGEND_GAP + w > content_w:
                rows.append([])
                used = 0.0
            used += (LEGEND_GAP if rows[-1] else 0) + w
            rows[-1].append(it)
        self._legend_rows = rows

        # ★ 没有编组资料时不画车厢行（否则右边空出一大块）
        if self._cars:
            row_h = (BADGE_H + BADGE_GAP + CAR_H) * self._car_scale
        else:
            row_h = 22
        body_h = (MARGIN + TITLE_H + GAP_TITLE
                  + row_h
                  + GAP_LEGEND + LEGEND_H * len(rows)
                  + MARGIN)
        self._content_w = int(content_w)
        self._body_h = int(body_h)
        self._w = int(content_w) + MARGIN * 2 + SHADOW_PAD * 2
        self._h = int(body_h) + SHADOW_PAD * 2
        self.setFixedSize(self._w, self._h)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self._w, self._h)

    # ------------------------------------------------------------ 事件
    # ★★ v2.6.4：原来这里有一个「✕ 显示全部」的命中区（`_btn_rect`）+
    #   悬浮高亮 + 点击发 `close_requested`。用户要求**删掉**它，
    #   把退出入口改成**地图右上角的红色大 ✕**（`ui/isolated_close_button.py`）。
    #   所以这一整块（命中区 / 悬浮态 / 点击）连同 `_draw_button` 一起删了 ——
    #   卡片现在**纯展示、不响应任何点击**。

    def enterEvent(self, event):
        self.setCursor(Qt.ArrowCursor)
        super().enterEvent(event)

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        card = QRectF(SHADOW_PAD, SHADOW_PAD, self._w - SHADOW_PAD * 2,
                      self._h - SHADOW_PAD * 2)

        # ★★ "融入背景"（用户要求：不要单独一个模块的样子）：
        #   ① 不画阴影 —— 阴影是"浮在地图上面"最强的观感来源
        #   ② 不画描边 —— 边框一有，就变成一个"卡片"
        #   ③ 底色 = **地图自己的底色 #F7F9FB**（不是纯白）。
        #      同色 + 无边框 + 无阴影 ⇒ 在地图上根本没有轮廓，
        #      只有压在彩色线路上的那一小块才看得出（必须挡，否则文字糊）。
        path = QPainterPath()
        path.addRoundedRect(card, 12, 12)
        p.setPen(Qt.NoPen)
        bg = QColor(CARD_BG)
        bg.setAlpha(CARD_ALPHA)
        p.setBrush(QBrush(bg))
        p.drawPath(path)

        x0 = card.left() + MARGIN
        y = card.top() + MARGIN

        # ---- 标题行：线路色块 + 线路名 · 车厢编组 ----
        sw = QRectF(x0, y + (TITLE_H - 13) / 2.0, 22, 13)
        sp = QPainterPath()
        sp.addRoundedRect(sw, 3.5, 3.5)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(self._line_color)))
        p.drawPath(sp)

        f_title = QFont(FONT_FAMILY, 9, QFont.Bold)
        p.setFont(f_title)
        p.setPen(QPen(QColor("#1E293B")))
        p.drawText(QRectF(x0 + 30, y, self._content_w - 30, TITLE_H),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   "%s · 车厢编组" % self._line_name)

        y += TITLE_H + GAP_TITLE

        if not self._cars:
            p.setFont(QFont(FONT_FAMILY, 8))
            p.setPen(QPen(QColor("#94A3B8")))
            p.drawText(QRectF(x0, y, self._content_w, 22),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       "这条线路暂无车厢编组资料。")
            p.end()
            return

        # ---- 车厢行（窄视口下整体缩放：以顶边中点为基准，图标/节号一起缩）----
        n = len(self._cars)
        car_w = n * CAR_W + (n - 1) * CAR_GAP
        cx = x0 + (self._content_w - car_w * self._car_scale) / 2.0
        s = self._car_scale
        p.save()
        p.translate(cx, y)
        p.scale(s, s)
        p.translate(-cx, -y)
        for i, kind in enumerate(self._cars):
            x = cx + i * (CAR_W + CAR_GAP)
            self._draw_badge(p, x, y, i + 1)
            self._draw_car(p, x, y + BADGE_H + BADGE_GAP,
                           i == 0, i == n - 1, kind)
        p.restore()

        y += (BADGE_H + BADGE_GAP + CAR_H) * s + GAP_LEGEND

        # ---- 图例行 ----
        for row in self._legend_rows:
            lx = x0
            for kind, _rng, text in row:
                self._draw_legend_icon(p, lx, y + (LEGEND_H - LEGEND_ICON) / 2.0, kind)
                p.setFont(QFont(FONT_FAMILY, 8))
                p.setPen(QPen(QColor("#475569")))
                tw = QFontMetrics(QFont(FONT_FAMILY, 8)).horizontalAdvance(text)
                p.drawText(QRectF(lx + LEGEND_ICON + 5, y,
                                  tw + 4, LEGEND_H),
                           Qt.AlignLeft | Qt.AlignVCenter, text)
                lx += LEGEND_ICON + 5 + tw + LEGEND_GAP
            y += LEGEND_H
        p.end()

    # ---------------------------------------------------------- 子绘制
    def _draw_badge(self, p: QPainter, x: float, y: float, n: int) -> None:
        r = QRectF(x + (CAR_W - BADGE_W) / 2.0, y, BADGE_W, BADGE_H)
        path = QPainterPath()
        path.addRoundedRect(r, 3, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#F2F2F4")))
        p.drawPath(path)
        p.setFont(QFont(FONT_FAMILY, 7, QFont.Bold))
        p.setPen(QPen(QColor("#B6BBC4")))
        p.drawText(r, Qt.AlignCenter, str(n))

    def _draw_car(self, p: QPainter, x: float, y: float,
                  first: bool, last: bool, kind: str) -> None:
        pal = PALETTE[kind]
        rl = NOSE_R if first else CAR_R
        rr = NOSE_R if last else CAR_R
        path = _car_path(x, y, CAR_W, CAR_H, rl, rr)
        p.setPen(QPen(QColor(pal["border"]), 1.2))
        p.setBrush(QBrush(QColor(pal["fill"])))
        p.drawPath(path)

        ccx, ccy = x + CAR_W / 2.0, y + CAR_H / 2.0
        if kind == BIZ:
            _draw_briefcase(p, ccx, ccy, 17, 14, QColor(pal["accent"]))
        else:
            _draw_snowflake(p, ccx, ccy, 7.4, QColor(pal["accent"]))

    def _draw_legend_icon(self, p: QPainter, x: float, y: float, kind: str) -> None:
        pal = PALETTE[kind]
        r = QRectF(x, y, LEGEND_ICON, LEGEND_ICON)
        path = QPainterPath()
        path.addRoundedRect(r, 3, 3)
        p.setPen(QPen(QColor(pal["border"]), 1))
        p.setBrush(QBrush(QColor(pal["fill"])))
        p.drawPath(path)
        c = r.center()
        if kind == BIZ:
            _draw_briefcase(p, c.x(), c.y(), 8, 7, QColor(pal["accent"]))
        else:
            _draw_snowflake(p, c.x(), c.y(), 3.8, QColor(pal["accent"]))


# ======================================================================
# 图形原语
# ======================================================================
def _car_path(x: float, y: float, w: float, h: float,
              rl: float, rr: float) -> QPainterPath:
    """四角半径可分别指定的圆角矩形（头车左端/尾车右端圆一点 = 车头轮廓）。"""
    rl = min(rl, w / 2.0, h / 2.0)
    rr = min(rr, w / 2.0, h / 2.0)
    p = QPainterPath()
    p.moveTo(x + rl, y)
    p.lineTo(x + w - rr, y)
    p.arcTo(x + w - 2 * rr, y, 2 * rr, 2 * rr, 90, -90)            # 右上
    p.lineTo(x + w, y + h - rr)
    p.arcTo(x + w - 2 * rr, y + h - 2 * rr, 2 * rr, 2 * rr, 0, -90)  # 右下
    p.lineTo(x + rl, y + h)
    p.arcTo(x, y + h - 2 * rl, 2 * rl, 2 * rl, 270, -90)             # 左下
    p.lineTo(x, y + rl)
    p.arcTo(x, y, 2 * rl, 2 * rl, 180, -90)                          # 左上
    p.closeSubpath()
    return p


def _draw_snowflake(p: QPainter, cx: float, cy: float, r: float,
                    color: QColor) -> None:
    """六向雪花：3 条直径 + 每个端点两段小枝（手画，不依赖字形）。"""
    pen = QPen(color)
    pen.setWidthF(max(1.1, r * 0.19))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    br = r * 0.44
    for k in range(6):
        a = math.radians(60 * k)
        ex, ey = cx + math.cos(a) * r, cy + math.sin(a) * r
        if k < 3:                                   # 三条直径只画一次
            p.drawLine(QPointF(cx - math.cos(a) * r, cy - math.sin(a) * r),
                       QPointF(ex, ey))
        for sgn in (1, -1):
            a2 = a + math.radians(38) * sgn
            p.drawLine(QPointF(ex, ey),
                       QPointF(ex - math.cos(a2) * br, ey - math.sin(a2) * br))


def _draw_briefcase(p: QPainter, cx: float, cy: float, w: float, h: float,
                    color: QColor) -> None:
    """公文包：主体 + 提手 + 中缝。"""
    pen = QPen(color)
    pen.setWidthF(max(1.0, w * 0.09))
    p.setPen(pen)

    body = QRectF(cx - w / 2.0, cy - h / 2.0 + h * 0.20, w, h * 0.80)
    bp = QPainterPath()
    bp.addRoundedRect(body, h * 0.11, h * 0.11)
    fill = QColor(color)
    fill.setAlpha(44)
    p.setBrush(QBrush(fill))
    p.drawPath(bp)

    hw = w * 0.40
    handle = QRectF(cx - hw / 2.0, body.top() - h * 0.26, hw, h * 0.30)
    hp = QPainterPath()
    hp.addRoundedRect(handle, h * 0.09, h * 0.09)
    p.setBrush(Qt.NoBrush)
    p.drawPath(hp)

    p.drawLine(QPointF(body.left() + w * 0.06, body.top() + body.height() * 0.36),
               QPointF(body.right() - w * 0.06, body.top() + body.height() * 0.36))
    p.setBrush(Qt.NoBrush)
