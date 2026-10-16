"""
ui/isolated_close_button.py
====================================
「退出『只看这一条线』」的**右上角红色大 ✕**（v2.6.4）。

为什么单独做成一个浮层控件：
原来这个"退出"入口是**右下角车厢编组卡片上的一行蓝字**（「✕ 显示全部」）——
用户原话：「双击对应线路右下方的 ❌ 显示全部，删掉，改为在右上角添加红色的大 ❌」。
两个问题：
  ① 卡片是"融入背景"的淡色块，上面的蓝字更淡，**根本不像个能点的东西**；
  ② 它挂在右下角，而人的视线进出这个模式时习惯看**右上角**（关闭按钮的位置）。

★ 这一颗**故意不"融入背景"** —— 它是**操作按钮**，不是信息卡片。
  用户明确要求"红色的大 ❌"，就该让人一眼看到。
  （和 MEMORY §4.4「浮层要融入背景」不冲突：那条讲的是**信息卡**别像独立模块。）

★ 位置由 `MapView._layout_chrome()` 在**每次绘制前**用当前视口尺寸校正
  （`register_chrome(btn, "tr")`），不要自己 move —— 自己算会读到上一帧的视口宽。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import QWidget


# 直径：比原来卡片上那行小字大得多（原按钮 70×20），一眼就能看到
BTN_SIZE = 44
# 底色：Material Red 600 / 800 / 900
COLOR_BASE = "#E53935"
COLOR_HOVER = "#C62828"
COLOR_PRESS = "#B71C1C"
# 外面套一圈白，压在地图的深色线路上也不会糊成一团
RING_COLOR = "#FFFFFF"
RING_W = 2.0


class IsolatedCloseButton(QWidget):
    """右上角的红色圆形 ✕：点击 = 退出「只看这一条线」。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("IsolatedCloseButton")
        self.setFixedSize(BTN_SIZE, BTN_SIZE)
        self.setCursor(Qt.PointingHandCursor)          # 抓手，明确可点
        self.setToolTip("退出「只看这一条线」\n（也可以再双击图例那一行，或按 Esc）")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self._hover = False
        self._pressed = False
        self.hide()

    # ------------------------------------------------------------ 事件
    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was = self._pressed
            self._pressed = False
            self.update()
            # ★ 只有"在按钮上按下、又在按钮上松开"才算点击
            #   （按下后拖出去再松开不该触发，跟系统按钮一致）
            if was and self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(RING_W, RING_W, -RING_W, -RING_W)

        fill = (COLOR_PRESS if self._pressed
                else COLOR_HOVER if self._hover else COLOR_BASE)

        # 白色外圈（先画大一圈的白圆，再画红色实心圆，等于描了一层白边）
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(RING_COLOR))
        p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        p.setBrush(QColor(fill))
        p.drawEllipse(r)

        # ✕ —— 白色粗线，两端圆头
        pen = QPen(QColor("#FFFFFF"))
        pen.setWidthF(3.0)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        c = r.center()
        d = r.width() * 0.22                        # 叉的半长
        for sx, sy in ((1, 1), (1, -1)):
            path = QPainterPath(QPointF(c.x() - d * sx, c.y() - d * sy))
            path.lineTo(QPointF(c.x() + d * sx, c.y() + d * sy))
            p.drawPath(path)
        p.end()
