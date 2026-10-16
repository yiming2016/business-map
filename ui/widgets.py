"""
ui/widgets.py
========================
几个 UI 复用小零件：

  · LinesPopup  —— "所属线路"展开后的候选面板（**一行 3 个**勾选项）
  · LinesSelect —— "所属线路"下拉多选：收起时显示已选线路，点一下展开候选面板
  · SearchSuggestPopup / SuggestRow —— 搜索框下方的候选面板（边打字边出结果）
  · make_add_image_icon / make_cover_icon / rounded_pixmap —— 画图标与缩略图

设计说明：
  "所属线路"原来是 20 个 QCheckBox 平铺，占地大又难扫。改成下拉后，
  收起状态直接显示"1号线 11号线"这样的结果（v2.4.14 起用空格分隔），展开才看到全部候选；
  展开面板用 3 列表格排（20 条线路 → 7 行），比一列长菜单省一大截高度。

  为什么不用 QMenu 装 QAction：
  QAction 在 QMenu 里只能**竖着一列**排，做不出 3 列网格，
  所以这里用一个 `Qt.Popup` 的无边框 QFrame + QGridLayout 自己搭。
  `Qt.Popup` 天然"点外面就关"，点里面的勾选框不会关，正好适合多选。

  搜索候选面板（v2.5.0）沿用同一套 `Qt.Popup` 做法，理由见 SearchSuggestPopup 的注释。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, QEvent, QPoint, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath,
    QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QScrollArea, QStyle, QStyleOptionToolButton, QToolButton, QVBoxLayout, QWidget,
)

# 展开面板一行放几个
POPUP_COLUMNS = 3

# 线路名字的默认色（取不到官方色时用）
LINE_TEXT_FALLBACK = "#333333"


def line_text_color(line: Optional[Dict]) -> str:
    """取一条线路的**官方颜色**（用于把线路名画成对应颜色）。

    ★ 项目约定：深圳地铁的线路色已存在 `lines.json` 的 `color` 字段里
      （`metro_render` 画线路时用的就是它）—— 这里直接读同一份数据，
      保证"下拉菜单里 2 号线的字"和"地图上 2 号线那条线"**永远是同一个颜色**。
    """
    c = (line or {}).get("color") or (line or {}).get("color_hex") or ""
    c = str(c).strip()
    return c if c.startswith("#") else LINE_TEXT_FALLBACK


# ------------------------------------------------------------
# 展开后的候选面板
# ------------------------------------------------------------
class LinesPopup(QFrame):
    """一行 3 个的勾选面板。勾选不关闭自己，点外面才关。"""

    toggled_line = Signal()

    def __init__(self, lines: Sequence[Dict], parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("LinesPopup")
        # QFrame 支持样式表的盒模型，背景/边框能正常画出来
        # （纯 QWidget 子类要 WA_StyledBackground 才行，容易踩坑）
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("""
            QFrame#LinesPopup {
                background: #ffffff;
                border: 1px solid #c8ccd4;
                border-radius: 6px;
            }
            QCheckBox { padding: 2px 3px; }
            QCheckBox:hover { background: #f2f7ff; border-radius: 3px; }
        """)

        grid = QGridLayout(self)
        grid.setContentsMargins(9, 9, 9, 9)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)

        self.checks: Dict[str, QCheckBox] = {}
        for i, ln in enumerate(lines):
            lid = ln.get("id")
            name = ln.get("name", lid or "?")
            alias = ln.get("alias") or ""
            text = f"{name}（{alias}）" if alias else str(name)
            cb = QCheckBox(text)
            # ★ v2.6.6：候选文字用**该线路的官方色**（用户要求）。
            #   加粗是为了让浅色线路（如 11 号线的棕、有轨电车的浅色）也有足够对比度。
            #   注意这是**控件级**样式表，会盖掉面板上那条 `QCheckBox{padding...}`，
            #   所以 padding / hover 要在这里一起写全，否则内边距会退化。
            cb.setStyleSheet(
                "QCheckBox { padding: 2px 3px; font-weight: 700; color: %s; }"
                "QCheckBox:hover { background: #f2f7ff; border-radius: 3px; }"
                % line_text_color(ln))
            cb.toggled.connect(self.toggled_line)
            self.checks[lid] = cb
            grid.addWidget(cb, i // POPUP_COLUMNS, i % POPUP_COLUMNS)

    # ---------- 对外 ----------
    def set_check(self, line_id: str, checked: bool) -> None:
        cb = self.checks.get(line_id)
        if cb is not None:
            cb.setChecked(checked)

    def selected_ids(self) -> List[str]:
        return [lid for lid, cb in self.checks.items() if cb.isChecked()]

    def checkboxes(self) -> List[QCheckBox]:
        return list(self.checks.values())


# ------------------------------------------------------------
# 所属线路：下拉多选
# ------------------------------------------------------------
class LinesSelect(QToolButton):
    """下拉多选线路。

    · 收起时按钮文字 = 已选线路名（`1号线 11号线`，空格分隔），没选显示"未选择"
    · 点一下展开 `LinesPopup`（一行 3 个候选），可连续勾选
    · 变化时发 `changed(list_of_line_ids)`
    """

    changed = Signal(list)

    EMPTY_TEXT = "未选择"
    # 收起时按钮文字最长显示多少字符。
    # v2.4.14：26 → 32 —— 4 条线路最长的一种照空格分隔是
    # "10号线 11号线 14号线 20号线" = 26 字符，原来的 26 会把它截成省略号，
    # 留到 32 给"5 条线 / 更长的线名"一点余量。
    MAX_TEXT_LEN = 32
    # v2.4.14：已选线路之间的分隔符。
    # 原来是顿号"、"，实测更宽（4 条线路：顿号 181px vs 空格 156px），
    # 用户也要求去掉顿号，改成**空格**。
    SEP = " "

    def __init__(self, lines: Sequence[Dict], selected: Optional[Sequence[str]] = None,
                 parent=None):
        super().__init__(parent)
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(28)
        # 不用 QMenu，靠 clicked 自己弹面板
        self.setPopupMode(QToolButton.DelayedPopup)
        self.setStyleSheet("""
            QToolButton {
                text-align: left;
                padding: 4px 24px 4px 8px;
                border: 1px solid #c8ccd4;
                border-radius: 4px;
                background: #ffffff;
            }
            QToolButton:hover { border-color: #90a4ae; }
            QToolButton::menu-indicator { image: none; }
            QToolButton::menu-button { width: 0px; border: none; }
        """)

        self._lines: List[Dict] = list(lines)
        self._popup = LinesPopup(self._lines, self)
        self._popup.toggled_line.connect(self._on_toggled)
        self.clicked.connect(self._toggle_popup)

        self.set_selected(selected or [])

    # ---------- 弹面板 ----------
    def _toggle_popup(self) -> None:
        if self._popup.isVisible():
            self._popup.hide()
            return
        self._popup.adjustSize()
        anchor = self.mapToGlobal(QPoint(0, self.height() + 2))
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(anchor.x(), area.right() - self._popup.width())
        y = anchor.y()
        if y + self._popup.height() > area.bottom():
            # 下面放不下就翻到按钮上方
            y = self.mapToGlobal(QPoint(0, 0)).y() - self._popup.height() - 2
        self._popup.move(max(area.left(), int(x)), max(area.top(), int(y)))
        self._popup.show()

    # ---------- 勾选联动 ----------
    def _on_toggled(self, _checked: bool = False) -> None:
        self._refresh_text()
        self.changed.emit(self.selected_ids())

    def _refresh_text(self) -> None:
        names = []
        segs = []                       # [(显示名, 颜色), ...] —— 给自绘用
        for act_id in self._popup.selected_ids():
            ln = self._line_of(act_id)
            nm = ln.get("name", str(act_id)) if ln else str(act_id)
            names.append(nm)
            segs.append((nm, line_text_color(ln)))
        text = self.SEP.join(names) if names else self.EMPTY_TEXT
        if len(text) > self.MAX_TEXT_LEN:
            text = text[: self.MAX_TEXT_LEN - 1] + "…"
        self.setText(text)              # 逻辑上仍保留纯文本（测试/工具提示都用它）
        self._segs = segs
        # ★ v2.7.11：去掉了开头的「已选：」四个字（用户原话「删除文字『已选：』，
        #   保留后面的线路」）。没选时仍给一句"（无）"，不然提示框是空的更费解。
        self.setToolTip(self.SEP.join(names) if names else "（无）")
        self.update()
        # ★ v2.7.11：右侧面板那格要**跟着当前线路名自适应宽度**（见 _fit_to_text）
        if getattr(self, "auto_fit_width", False):
            self._fit_to_text()

    # ---------- 宽度自适应（v2.7.11） ----------
    #: 打开后，宽度随"当前显示的线路名"变化（右侧面板用；编辑弹窗不用）
    auto_fit_width = False
    MIN_FIT_W = 150
    MAX_FIT_W = 258

    def _fit_to_text(self) -> None:
        """把宽度调成**正好装下当前那串线路名**（v2.7.11）。

        ★ 起因（用户原话）：「右侧弹窗适当压缩所属区的下拉菜单横向长度，
          目的是让左侧包含线路的下拉菜单内容显示完整」。
          原来这格是**死宽 150px**，而"2号线 10号线 11号线 14号线"（岗厦北）
          实测要 ~250px ⇒ 后面的线路被 `_paint_line_names` 省略号吃掉。
        ★ 量的是 `self.text()`（= 真正会画出来的那一串），所以只要宽度 ≥ 需要值，
          就**一定不会省略**；两端留白用与绘制同一套常量（TEXT_LEFT/TEXT_RIGHT），
          换了字号/内边距也不会对不上。
        """
        need = (QFontMetrics(self.font()).horizontalAdvance(self.text())
                + self.TEXT_LEFT + self.TEXT_RIGHT)
        self.setFixedWidth(int(max(self.MIN_FIT_W,
                                  min(self.MAX_FIT_W, need))))

    # ---------- 已选线路名：按各自线路色画 ----------
    # ★ 为什么不用 `super().paintEvent()` 直接让它画文字：
    #   `QToolButton` 的文字**只能是一种颜色**，而"2 号线红、5 号线紫"必须并存。
    #   所以让样式层只画底与边框（把 opt.text 清空），文字我们自己逐段画。
    TEXT_LEFT = 9        # 左边框 1px + padding-left 8px
    TEXT_RIGHT = 25      # 右边框 1px + padding-right 24px（小三角就画在这一带）
    EMPTY_COLOR = "#90a4ae"

    def _paint_line_names(self, p: QPainter) -> None:
        f = QFont(self.font())
        p.setFont(f)
        fm = QFontMetrics(f)
        x0 = self.TEXT_LEFT
        right = max(x0 + 12, self.width() - self.TEXT_RIGHT)
        baseline = int((self.height() + fm.ascent() - fm.descent()) / 2)
        segs = getattr(self, "_segs", None) or [(self.EMPTY_TEXT, self.EMPTY_COLOR)]
        x = x0
        for i, (txt, col) in enumerate(segs):
            s = txt if i == 0 else (self.SEP + txt)
            if x + fm.horizontalAdvance(s) > right:
                remain = right - x
                if remain < fm.horizontalAdvance("…"):
                    break
                s = fm.elidedText(s, Qt.ElideRight, remain)
            p.setPen(QColor(col))
            p.drawText(x, baseline, s)
            x += fm.horizontalAdvance(s)
            if x >= right:
                break

    def _line_of(self, line_id) -> Optional[Dict]:
        for ln in self._lines:
            if ln.get("id") == line_id:
                return ln
        return None

    # ---------- 自绘：底色交给样式层，文字按线路配色，右侧补小三角 ----------
    def paintEvent(self, event) -> None:
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        opt.text = ""       # ★ 关键：不让默认绘制画那行单色文字
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        self.style().drawComplexControl(
            QStyle.ComplexControl.CC_ToolButton, opt, p, self)
        self._paint_line_names(p)
        p.setPen(QPen(QColor("#607d8b"), 1.6))
        cx = self.width() - 13.0
        cy = self.height() / 2.0 - 1.0
        p.drawLine(QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2))
        p.drawLine(QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2))
        p.end()

    # ---------- 对外 API ----------
    def selected_ids(self) -> List[str]:
        return self._popup.selected_ids()

    def set_selected(self, ids: Sequence[str]) -> None:
        want = set(ids or [])
        for lid, cb in self._popup.checks.items():
            cb.blockSignals(True)
            cb.setChecked(lid in want)
            cb.blockSignals(False)
        self._refresh_text()

    def set_line_checked(self, line_id: str, checked: bool = True) -> None:
        """单独勾/取消一条线路（会正常触发 changed）。"""
        self._popup.set_check(line_id, checked)

    def clear_selection(self) -> None:
        self.set_selected([])

    def line_checks(self) -> List[QCheckBox]:
        """给测试/外部检查用：展开面板里的所有勾选框。"""
        return self._popup.checkboxes()

    def popup_columns(self) -> int:
        return POPUP_COLUMNS


# ------------------------------------------------------------
# 搜索下拉：边打字边出候选
# ------------------------------------------------------------
# 面板宽度。搜索框本身只有 160px，候选行还要放下「站名 + 所属线路」，给宽一点。
SUGGEST_WIDTH = 280
SUGGEST_ROW_H = 30
# 不滚动时最多显示几行，更长的出滚动条
SUGGEST_VISIBLE_ROWS = 8
# 最多建多少行。实测本图 379 个站里，单字查询最多命中 24 条（"园" 24 / "南" 22），
# 40 足够把所有真实结果一次列完。
SUGGEST_MAX_ROWS = 40

_ROW_BG = "transparent"
_ROW_BG_HOVER = "#f0f6ff"
_ROW_BG_ACTIVE = "#dbeaff"


def _row_qss(bg: str, hover: str) -> str:
    """候选行的样式。

    ★ 样式表设在**行自己**身上，不靠父级级联：
      这样 Qt 会自动为该行打开 WA_Hover，`:hover` 才真的生效。
    """
    return (f"QFrame#SuggestRow {{ background: {bg}; border-radius: 4px; }}"
            f"QFrame#SuggestRow:hover {{ background: {hover}; }}")


class SuggestRow(QFrame):
    """候选面板里的一行：左边站名（深色粗体），右边所属线路（灰色小字）。"""

    clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SuggestRow")
        self.setFixedHeight(SUGGEST_ROW_H)
        self.setCursor(Qt.PointingHandCursor)
        # 不可聚焦：焦点一旦跑进面板内部，按键就会被面板内部吃掉（见 SearchSuggestPopup）
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet(_row_qss(_ROW_BG, _ROW_BG_HOVER))

        h = QHBoxLayout(self)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(8)

        self.lbl_name = QLabel("-", self)
        self.lbl_name.setStyleSheet(
            "QLabel { color: #263238; font-size: 13px; font-weight: bold; }")
        self.lbl_info = QLabel("", self)
        self.lbl_info.setStyleSheet("QLabel { color: #90a4ae; font-size: 11px; }")
        h.addWidget(self.lbl_name)
        h.addStretch(1)
        h.addWidget(self.lbl_info)

        self.station_id = ""
        self._active = False

    def set_content(self, station_id: str, name: str, info: str = "") -> None:
        self.station_id = station_id
        self.lbl_name.setText(name)
        self.lbl_info.setText(info)

    def text(self) -> str:
        return self.lbl_name.text()

    def info_text(self) -> str:
        return self.lbl_info.text()

    def is_active(self) -> bool:
        return self._active

    def set_active(self, on: bool) -> None:
        """键盘上下移动时的"当前行"高亮。"""
        on = bool(on)
        if on == self._active:
            return
        self._active = on
        self.setStyleSheet(_row_qss(_ROW_BG_ACTIVE if on else _ROW_BG,
                                    _ROW_BG_ACTIVE if on else _ROW_BG_HOVER))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.station_id:
            self.clicked.emit(self.station_id)
        super().mouseReleaseEvent(event)


class SearchSuggestPopup(QFrame):
    """搜索框正下方的候选面板。

    为什么用 `Qt.Popup`（而不是普通无边框窗口）——都是实测出来的：
      · 点面板外面任何地方 → Qt 自动关掉，不用自己监听全局鼠标；
      · 面板里的滚轮也能正常滚（实测滚动条 0 → 180）。

    ★★ 代价：`Qt.Popup` 会把**按键**抢过去。弹层一出现，Qt 就把键盘事件
      重定向给它（QApplication 的弹层规则，QMenu/QComboBox 同理），
      搜索框一个字都收不到 —— v2.5.0 就栽在这里，用户报的原话是
      「每次输入完成后怎么就取消输入了？每删除一个文字也会变成取消输入」。
      所以必须做两件事：把按键转发回搜索框（见 keyPressEvent），
      并且面板里**不能有可聚焦的子控件**（否则焦点会被吸进面板内部，
      见下面 _area.setFocusPolicy 那段）。

    ★ 注意区分两件事 —— 我在这上面判断错过一次，代价是让用户白跑了一版：
        · **焦点**不会丢：弹层弹出后 `focusWidget()` 仍是搜索框、
          Win32 键盘焦点仍压在主窗口上（所以中文输入法照常组字）。
          这是拿**真实的 MainWindow** 实测的（tools/_probe_real_focus.py）。
        · **按键**会被抢走：Qt 把键盘事件重定向给弹层。
      「焦点还在」≠「按键进得去」。所以要验"能不能继续打字"，
      必须发**窗口级**按键（`QTest.keyClick(窗口, ...)`）；
      发到控件上会把事件直接塞给控件、绕过 Qt 的分发，测出来是假的。

    ★ 性能：候选行用「行池」复用 —— 只改文字，不销毁重建。
      实测 40 行重建一次：全删重建 4.6ms，行池复用 0.43ms。
      逐键动作越省越好（本项目出过"打字未响应"）。
      逐键真实成本：接着敲每键 2~4ms、卡片改高度 0.66ms、只重绘 0.70ms
      （tools/_probe_type_cost.py）。
    """

    picked = Signal(str)

    def __init__(self, parent=None, key_target: Optional[QWidget] = None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("SearchSuggest")
        # QFrame 支持样式表的盒模型，背景/边框能正常画出来
        # （纯 QWidget 子类要 WA_StyledBackground 才行，容易踩坑）
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(
            "QFrame#SearchSuggest { background: #ffffff;"
            " border: 1px solid #c8ccd4; border-radius: 6px; }"
        )
        self.setFixedWidth(SUGGEST_WIDTH)

        # ★★ v2.5.1：按键要转发给谁（也就是那个搜索框）。见 keyPressEvent 的注释。
        self._key_target: Optional[QWidget] = key_target

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(3)

        # 候选行都塞进 body，body 再放进滚动区（结果多时可滚）
        self._body = QWidget()
        self._bodyv = QVBoxLayout(self._body)
        self._bodyv.setContentsMargins(0, 0, 0, 0)
        self._bodyv.setSpacing(1)

        self._area = QScrollArea(self)
        self._area.setObjectName("SuggestArea")
        self._area.setWidgetResizable(True)
        self._area.setFrameShape(QFrame.NoFrame)
        self._area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._area.setWidget(self._body)
        # ★★ v2.5.1：滚动区默认是**可以拿焦点**的（WheelFocus）。
        #   一旦焦点落进面板内部，按键就先被它吃掉（↑↓ 变成滚列表），
        #   搜索框一个字都收不到 —— 用户看到的正是"输入被取消了"。
        #   所以面板里所有子控件一律设成不可聚焦，按键才始终走"转发回搜索框"这条路。
        self._area.setFocusPolicy(Qt.NoFocus)
        self._body.setFocusPolicy(Qt.NoFocus)
        # 再加一道保险：万一以后有子控件拿到焦点，也把按键转回去（见 eventFilter）
        self._area.installEventFilter(self)
        self._area.viewport().installEventFilter(self)
        # 去掉滚动区自带的白底/边框，只留外层面板那一层；
        # 顺手把滚动条改细（默认那条又宽又带箭头，跟界面不搭）
        self._area.setStyleSheet(
            "QScrollArea#SuggestArea { background: transparent; border: none; }"
            "QScrollArea#SuggestArea > QWidget > QWidget { background: transparent; }"
            "QScrollBar:vertical { background: transparent; width: 9px; margin: 0; }"
            "QScrollBar::handle:vertical { background: #b0bec5; border-radius: 4px;"
            " min-height: 24px; }"
            "QScrollBar::handle:vertical:hover { background: #78909c; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
            " background: transparent; }"
        )
        root.addWidget(self._area)

        # 底部状态行：无匹配 / 结果被截断时的提示。不需要时整行藏起来
        self.lbl_note = QLabel("", self)
        self.lbl_note.setObjectName("SuggestNote")
        self.lbl_note.setFocusPolicy(Qt.NoFocus)
        self.lbl_note.setStyleSheet(
            "QLabel#SuggestNote { color: #90a4ae; font-size: 11px; padding: 2px 4px; }")
        self.lbl_note.hide()
        root.addWidget(self.lbl_note)

        self._rows: List[SuggestRow] = []
        self._active = -1

    # ---------- 内容 ----------
    def set_items(self, items: Sequence[Sequence[str]], total: int = -1) -> None:
        """填候选。items = [(station_id, 站名, 线路小字), ...]（调用方已按匹配度排好）。"""
        n = len(items)
        # 行不够就补，多了只藏不删 —— 这就是"行池"
        while len(self._rows) < n:
            row = SuggestRow(self._body)
            row.clicked.connect(self._on_row_clicked)
            self._bodyv.addWidget(row)
            self._rows.append(row)
        for i, it in enumerate(items):
            parts = list(it) + ["", "", ""]
            row = self._rows[i]
            row.set_content(str(parts[0]), str(parts[1]), str(parts[2]))
            row.show()
        for row in self._rows[n:]:
            row.set_active(False)
            row.hide()

        if total < 0:
            total = n
        if n == 0:
            self.lbl_note.setText("无匹配站点")
            self.lbl_note.show()
        elif total > n:
            self.lbl_note.setText(f"共 {total} 条，继续输入可缩小范围")
            self.lbl_note.show()
        else:
            self.lbl_note.hide()

        self._active = -1
        self._area.verticalScrollBar().setValue(0)
        self._apply_size()

    # ---------- 尺寸 ----------
    def _apply_size(self) -> None:
        """按内容精确算高度，不靠 `adjustSize()`。

        ★ 踩过的坑（2026-09-25 量出来的）：
          改完子控件高度后立刻 `adjustSize()`，拿到的是**旧尺寸** ——
          实测 2 行候选时 `sizeHint()` 已算成 78，窗口却停在 100；
          0 行时算成 37，窗口仍是 100（一个 280x100 的大白卡片里只有一行灰字）。
          内容尺寸本来就完全可算，直接自己算出来 `setFixedHeight` 最稳，
          也省得依赖布局的延迟激活时机。
        """
        visible = self.visible_rows()
        rows_shown = min(len(visible), SUGGEST_VISIBLE_ROWS)
        area_h = rows_shown * (SUGGEST_ROW_H + 1) + 2
        self._area.setFixedHeight(area_h)
        # 0 行时把滚动区整个藏掉：否则它会占着最小高度，卡片底部空一大块
        self._area.setVisible(rows_shown > 0)

        top = bottom = 6
        gap = self.layout().spacing() if self.note_visible() else 0
        note_h = (self.lbl_note.sizeHint().height() + gap) if self.note_visible() else 0
        self.setFixedHeight(top + (area_h if rows_shown > 0 else 0) + note_h + bottom)

    # ---------- 弹出 ----------
    def show_at(self, anchor: QWidget) -> None:
        """贴到 anchor 正下方显示；右边放不下就左移，下面放不下就翻到上方。

        尺寸已在 `_apply_size()` 里定死，这里不调 `adjustSize()`
        （见那里的注释：刚改完子控件高度时 `adjustSize()` 会拿到旧尺寸）。

        ★ 位置没变就别再动原生窗口（v2.5.1）：面板每收到一个字都会调到这里，
          而 `move()`/`raise_()` 落到 Windows 上都是一次 `SetWindowPos`。
          位置没变还去动它，等于用户每敲一个字都让系统重排一次窗口 ——
          实测这种多余动作会把单键耗时从个位数毫秒抬到几十毫秒。
        """
        tip = anchor.mapToGlobal(QPoint(anchor.width() // 2 - self.width() // 2,
                                        anchor.height() + 3))
        screen = QApplication.screenAt(tip) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        # ★★ v2.6.89：候选面板必须待在**软件窗口里面** —— 用户截图：
        #   面板伸出主窗口下沿悬在桌面上。原来只按"屏幕"夹，现在把夹取范围
        #   收缩到主窗口客户区（geometry()，不含标题栏边框）∩ 屏幕可用区。
        #   窗口太小/拿不到时退回屏幕范围，零风险。
        win = anchor.window()
        if win is not None:
            wg = win.geometry()
            if wg.isValid() and wg.width() > 60 and wg.height() > 60:
                area = area.intersected(wg)
        x = min(tip.x(), area.right() - self.width() - 4)
        y = tip.y()
        if y + self.height() > area.bottom():
            y = anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 3
            if y < area.top():
                y = max(area.top(), area.bottom() - self.height())
        pos = QPoint(max(area.left() + 4, int(x)), max(area.top() + 4, int(y)))

        if self.isVisible():
            if self.pos() != pos:
                self.move(pos)
            return                    # 已经在显示：位置没变就什么也不用做
        self.move(pos)
        self.show()
        self.raise_()

    # ---------- 点选 ----------
    def _on_row_clicked(self, station_id: str) -> None:
        self.picked.emit(station_id)

    # ---------- 键盘（按键留在搜索框，由主窗口转发进来） ----------
    def set_key_target(self, widget: Optional[QWidget]) -> None:
        """设置"按键转发给谁"（搜索框）。"""
        self._key_target = widget

    def key_target(self) -> Optional[QWidget]:
        return self._key_target

    def keyPressEvent(self, event) -> None:
        """把按键**转发回搜索框**。

        ★★ v2.5.1 修的 bug —— 用户原话：
             「每次输入完成后怎么就取消输入了？每删除一个文字也会变成取消输入」

        原因：本面板是 `Qt.Popup`。这类弹窗天生"把键盘抓到自己手里"：
        弹层一出现，用户接着打的**字、退格、上下键全都被弹层吃掉**，
        输入框再也收不到 —— 表现就是"输入到一半被取消了"。
        （QMenu / QComboBox 的下拉都是这个脾气；QComboBox 的可编辑下拉
          之所以还能继续打字，就是因为它的弹层把按键转发回去了。）

        ★ 为什么之前的测试没发现：用 `QTest.keyClick(输入框, ...)` 是把事件
          **直接塞给输入框**的，绕过了 Qt 的按键分发，所以测出来"一切正常"。
          必须用 `QTest.keyClick(窗口, ...)`（走窗口级分发）才测得出。
          回归脚本 `tools/_chk_search_suggest.py` 的 G 段就是为此加的。
        """
        tgt = self._key_target
        if tgt is not None and self.isVisible():
            QApplication.sendEvent(tgt, event)
            if event.isAccepted():
                return
        super().keyPressEvent(event)

    def event(self, ev) -> bool:
        # 输入法事件若落到弹层上，也转发给搜索框 —— 否则组字内容进不去
        if (ev.type() == QEvent.InputMethod and self._key_target is not None
                and self.isVisible()):
            QApplication.sendEvent(self._key_target, ev)
            if ev.isAccepted():
                return True
        return super().event(ev)

    def eventFilter(self, obj, ev) -> bool:
        """保险：万一面板内部哪个子控件拿到了焦点，按键也要转回搜索框。

        （面板和它的子控件本来都设成 NoFocus 了，正常轮不到这里；
          留着是为了"以后有人加了个可聚焦控件"时不会又变成"输入被取消"。）
        """
        if (ev.type() == QEvent.KeyPress and self._key_target is not None
                and self.isVisible()):
            QApplication.sendEvent(self._key_target, ev)
            if ev.isAccepted():
                return True
        return super().eventFilter(obj, ev)

    # ---------- 焦点兜底 ----------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._ensure_key_focus()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._ensure_key_focus()

    def _ensure_key_focus(self) -> None:
        """保证键盘有个归属。

        ★ v2.5.1：本面板是 `Qt.Popup`，弹出后会成为 Qt 的活动窗口。
          万一此时全应用**一个焦点控件都没有**，按键就"无处可送"——
          用户会发现一个字都打不进去（要点一下搜索框才恢复）。
          实测在特定状态下确实会出现 `focusWidget() is None`。

        只在"焦点真的丢了"（全应用没有焦点控件）时才补，
        **不去抢**用户主动点在地图上的焦点 —— 否则点地图后 ↑↓ 导航会失灵。
        """
        tgt = self._key_target
        if tgt is None:
            return
        if QApplication.focusWidget() is None:
            tgt.setFocus(Qt.OtherFocusReason)

    def move_active(self, delta: int) -> None:
        rows = self.visible_rows()
        if not rows:
            return
        if self._active < 0:
            new = 0 if delta > 0 else len(rows) - 1
        else:
            new = self._active + delta
        self._set_active(max(0, min(new, len(rows) - 1)))

    def _set_active(self, idx: int) -> None:
        rows = self.visible_rows()
        for i, row in enumerate(rows):
            row.set_active(i == idx)
        self._active = idx
        if 0 <= idx < len(rows):
            self._area.ensureWidgetVisible(rows[idx])

    def active_station_id(self) -> str:
        rows = self.visible_rows()
        if 0 <= self._active < len(rows):
            return rows[self._active].station_id
        return ""

    # ---------- 给测试/外部看 ----------
    def visible_rows(self) -> List[SuggestRow]:
        return [r for r in self._rows if not r.isHidden()]

    def rows(self) -> List[SuggestRow]:
        return list(self._rows)

    def note_text(self) -> str:
        """底部提示的文字（不管面板当下显示没显示，都返回真实文字）。"""
        return self.lbl_note.text()

    def note_visible(self) -> bool:
        """底部提示是否被设为显示。

        ★ 用 isHidden() 而不是 isVisible()：面板本身没 show 的时候，
          isVisible() 会因为父窗口不可见而一律返回 False，测不准。
        """
        return not self.lbl_note.isHidden()

    def active_index(self) -> int:
        return self._active

    def area(self) -> QScrollArea:
        return self._area

    def area_visible(self) -> bool:
        """滚动区是否被设为显示（同样用 isHidden()，理由见 note_visible）。"""
        return not self._area.isHidden()


# ------------------------------------------------------------
# 封面图图标
# ------------------------------------------------------------
def make_add_image_icon(size: int = 30, color: str = "#1976d2") -> QIcon:
    """画一个"添加图片"图标：相框 + 小太阳 + 山 + 右下角加号徽标。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    c = QColor(color)
    stroke = max(1.5, size * 0.065)
    pen = QPen(c, stroke)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)

    # 相框（右下角留出加号的位置）
    m = size * 0.12
    frame = QRectF(m, m, size - 2 * m - size * 0.16, size - 2 * m - size * 0.16)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(frame, size * 0.14, size * 0.14)

    # 小太阳
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    r = size * 0.062
    p.drawEllipse(QPointF(frame.left() + frame.width() * 0.30,
                          frame.top() + frame.height() * 0.30), r, r)

    # 山（两段折线）
    p.setBrush(Qt.NoBrush)
    p.setPen(pen)
    mp = QPainterPath()
    mp.moveTo(frame.left() + frame.width() * 0.08, frame.bottom() - frame.height() * 0.16)
    mp.lineTo(frame.left() + frame.width() * 0.38, frame.top() + frame.height() * 0.46)
    mp.lineTo(frame.left() + frame.width() * 0.58, frame.bottom() - frame.height() * 0.16)
    mp.moveTo(frame.left() + frame.width() * 0.60, frame.bottom() - frame.height() * 0.16)
    mp.lineTo(frame.left() + frame.width() * 0.74, frame.top() + frame.height() * 0.62)
    mp.lineTo(frame.right() - frame.width() * 0.06, frame.bottom() - frame.height() * 0.16)
    p.drawPath(mp)

    # 右下角加号徽标
    br = size * 0.20
    bc = QPointF(size - br - stroke * 0.6, size - br - stroke * 0.6)
    p.setPen(QPen(QColor("#ffffff"), stroke * 0.9))
    p.setBrush(QBrush(c))
    p.drawEllipse(bc, br, br)
    p.setPen(QPen(QColor("#ffffff"), max(1.6, size * 0.07)))
    p.drawLine(QPointF(bc.x() - br * 0.45, bc.y()), QPointF(bc.x() + br * 0.45, bc.y()))
    p.drawLine(QPointF(bc.x(), bc.y() - br * 0.45), QPointF(bc.x(), bc.y() + br * 0.45))

    p.end()
    return QIcon(pm)


def rounded_pixmap(path, w: int, h: int, radius: int = 10,
                   keep_aspect: bool = True) -> QPixmap:
    """读图 → 缩放到 (w,h) → 圆角裁剪。失败返回空 QPixmap。"""
    if path is None:
        return QPixmap()
    pm = QPixmap(str(path))
    if pm.isNull():
        return QPixmap()

    if keep_aspect:
        pm = pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (pm.width() - w) // 2)
        y = max(0, (pm.height() - h) // 2)
        pm = pm.copy(x, y, w, h)
    else:
        pm = pm.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    out = QPixmap(w, h)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing, True)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(clip)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


def make_cover_icon(path, size: int = 30) -> QIcon:
    """把封面图做成按钮图标（方形圆角缩略图）。没有图返回空 QIcon。"""
    pm = rounded_pixmap(path, size, size, radius=int(size * 0.20))
    return QIcon(pm) if not pm.isNull() else QIcon()


def make_nursing_icon(size: int = 20) -> QIcon:
    """★ v2.7.0：母婴室标记 —— 奶嘴小图标（有母婴室的站，挂在「所属区」下拉右侧）。

    形状取自"奶嘴"：中间横向挡板 + 上方乳头小圆头 + 下方圆底座，粉色系。
    用户原话：「把有母婴室的站点，所属区的下拉菜单的右侧增添一个奶嘴的图标即可」。
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    w = float(size)
    pink = QColor("#F4A6BC")
    deep = QColor("#E2679A")
    p.setBrush(deep)                                        # 挡板（中部横向）
    p.drawEllipse(QRectF(w * 0.08, w * 0.40, w * 0.84, w * 0.26))
    p.setBrush(pink)                                        # 乳头（上方小圆头）
    p.drawEllipse(QRectF(w * 0.33, w * 0.06, w * 0.34, w * 0.38))
    p.setBrush(pink)                                        # 底座（下方圆盘）
    p.drawEllipse(QRectF(w * 0.24, w * 0.58, w * 0.52, w * 0.34))
    p.end()
    return QIcon(pm)
