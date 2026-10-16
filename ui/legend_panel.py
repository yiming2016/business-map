"""
ui/legend_panel.py
========================
左侧线路图例面板。

每行：颜色条 + 线路名 + 别名 + 站数
交互：
  鼠标悬停 → 地图上对应线路加粗高亮（发 line_hovered）
  单击     → 把地图缩放到该线路范围（发 line_clicked）
  双击     → 地图上**只显示这一条线路**（发 line_double_clicked）；
             再双击一次 / 点**地图右上角的红色 ✕** 退出（v2.6.4 起）
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QPainter, QBrush, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QSizePolicy,
)


class LineRow(QFrame):
    """图例中的一行。"""

    hovered = Signal(str)
    clicked = Signal(str)
    double_clicked = Signal(str)

    def __init__(self, line: dict, station_count: int, parent=None):
        super().__init__(parent)
        self.line_id = line["id"]
        self.color = line.get("color", "#888888")
        self.setObjectName("LineRow")
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self._isolated = False
        self._apply_style()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(8)

        # 颜色条
        self.swatch = QWidget()
        self.swatch.setFixedSize(22, 12)
        self.swatch.setStyleSheet(
            f"background:{self.color}; border-radius:3px;"
        )
        lay.addWidget(self.swatch)

        # 线路名
        self.lbl_name = QLabel(line.get("name", ""))
        f = QFont("Microsoft YaHei", 9, QFont.Bold)
        self.lbl_name.setFont(f)
        lay.addWidget(self.lbl_name)

        # 别名
        alias = line.get("alias", "")
        self.lbl_alias = QLabel(alias)
        self.lbl_alias.setStyleSheet("color:#64748B; font-size:11px;")
        lay.addWidget(self.lbl_alias)

        lay.addStretch()

        # 站数
        self.lbl_cnt = QLabel(str(station_count))
        self.lbl_cnt.setStyleSheet("color:#94A3B8; font-size:10px;")
        lay.addWidget(self.lbl_cnt)

    def enterEvent(self, event):
        self.hovered.emit(self.line_id)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit("")
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.line_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit(self.line_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ---- 「单独显示」的选中态 ----
    def _apply_style(self) -> None:
        # ★ 常态也留一条 3px 的透明左边框：否则"单独显示"时多出来的这条边框
        #   会把整行内容往右推 3px，看起来像列表抖了一下。
        if self._isolated:
            self.setStyleSheet(
                "QFrame#LineRow { border-radius: 4px; padding: 2px;"
                " background: #DCEBFF; border-left: 3px solid %s; }"
                "QFrame#LineRow:hover { background: #D2E5FF; }" % self.color)
        else:
            self.setStyleSheet(
                "QFrame#LineRow { border-radius: 4px; padding: 2px;"
                " border-left: 3px solid transparent; }"
                "QFrame#LineRow:hover { background: #E8F0FE; }")

    def set_isolated(self, on: bool) -> None:
        if on == self._isolated:
            return
        self._isolated = on
        self._apply_style()


class LegendPanel(QWidget):
    line_hovered = Signal(str)
    line_clicked = Signal(str)
    line_double_clicked = Signal(str)
    reset_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # ★ v2.6.79：底部要常驻缩放双滑块（宽 ~180 + 左右留白），最窄从 180 放宽到 196
        self.setMinimumWidth(196)
        self.setMaximumWidth(260)
        self.setStyleSheet("background:#FFFFFF;")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 10, 8, 10)
        root.setSpacing(6)
        self.root = root          # ★ v2.6.79：add_persistent_bottom 要用

        # ★ v2.6.11：用户要求**删掉左上角「🚇 线路图例」标题 + 下面那行
        #   「悬停查看 · 单击定位 · 双击只看这条」提示**（连分隔线一起）。
        #   ⇒ 图例区直接从线路行开始，不留任何说明文字。
        #   注意：`set_isolated()` 原来会往 `self.lbl_hint` 上写状态文案，
        #   那行字也一并去掉了（"单独显示"由该行的左侧色条表示，够用了）。

        # 滚动区
        host = QWidget()
        self.vbox = QVBoxLayout(host)
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.setSpacing(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, 1)

        self._rows = []
        self._isolated_id = ""

    def add_persistent_bottom(self, widget: QWidget) -> None:
        """★ v2.6.79：往图例栏底部挂一个**常驻**控件（缩放双滑块）。

        · 挂在滚动区之下，不随线路列表滚动 —— 「最下方常驻」；
        · set_lines() 重建行只清 self.vbox，碰不到这个槽，不会被打扫掉。
        """
        self.root.addWidget(widget, 0)

    def add_persistent_top(self, widget: QWidget) -> None:
        """★ v2.7.1：往图例栏**顶部**挂一个常驻控件（搜索框）。

        用户原话：「把上方主工具栏的搜索站点名的框移动到左侧线路图例
        （1 号线的上方）」⇒ 插在滚动区之前（index 0），也就是线路行的上面。
        同理不会被 set_lines() 重建冲掉。
        """
        self.root.insertWidget(0, widget, 0)

    def set_lines(self, lines, stations: dict) -> None:
        # 清空
        while self.vbox.count():
            it = self.vbox.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
        self._rows.clear()

        for ln in lines:
            seq = ln.get("stations") or []
            row = LineRow(ln, len(seq))
            row.hovered.connect(self.line_hovered.emit)
            row.clicked.connect(self.line_clicked.emit)
            row.double_clicked.connect(self.line_double_clicked.emit)
            self.vbox.addWidget(row)
            self._rows.append(row)

        self.vbox.addStretch()

        # ★ 重建行之后要把"单独显示"的选中态贴回去 —— 否则保存/导入刷新图例时，
        #   地图还在只看一条线，左边却已经没有选中标记了（状态对不上）。
        self.set_isolated(getattr(self, "_isolated_id", ""))

    def set_isolated(self, line_id: str) -> None:
        """标记哪一行处于「单独显示」状态（空串 = 没有）。"""
        self._isolated_id = line_id or ""
        for row in self._rows:
            row.set_isolated(row.line_id == self._isolated_id)
        # （v2.6.11：原来这里还会改 `lbl_hint` 的文案，提示行已删除）
