"""
ui/exits_editor.py
==============================
「出入口信息」字段的专用编辑器（v2.6.3 做在 EditDialog 里，v2.6.5 抽成独立控件）。

为什么抽出来：同一个字段在**两个地方**出现（编辑弹窗 + 右侧信息面板）。
两份代码 = 同一个 bug 修两遍、还容易只修一处（skill §1b 末的教训）。
现在两边都用这一个控件，解析/拼回逻辑只有一份。

形态（**UI 拆开显示，存储格式一行都没改**）：

    A1      龙岗大道南侧、xxxxxxx
    B       宝安大道

★ 铁律（与 ui/timetable_editor.py 同一条）：
   **没动过的行必须原样吐回**。一律按 "编号 + 出入口：+ 内容" 重拼，
   会把数据里那些非标准写法悄悄改写 ——
   用户什么都没改、点一下保存，数据就变了。见 `ExitsEditor.text()`。
"""

from __future__ import annotations

import re
from typing import List

from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QStackedWidget,
    QPlainTextEdit, QPushButton, QSizePolicy, QLabel,
)

from ui.autofit import fit_height, min_height_for_lines

# ---------------- 编号列 ----------------
# ★ 编号列用 **QLineEdit 但画成标签的样子**（无边框、透明底、可聚焦）。
#   为什么不用 QLabel：不能编辑，用户就没法改编号、也没法补一个出口。
#   为什么不用普通输入框：那就还是"一个输入框"，没有"独立出去"的观感。
# ★ v2.7.7：用户要"编号列改成现在长度的 80%" ⇒ 46 × 0.8 ≈ 37。
#   只动**基础宽度**：长编号（`14a、14b、14c`）仍按实测宽度走 `calc_tag_width`，
#   不会跟着缩 80% 而被截断（见 calc_tag_width）。
EXIT_TAG_W = 37          # 编号列宽（够放 "A12" 这种两位数编号）
# ★ 字号/字重必须用 **QFont** 设，不能只写在样式表里（踩过）：
#   样式表里的 `font-size` **不会**反映到 `widget.font()`，于是
#   `font().pointSizeF()` 返回 −1 —— 任何"编号字号确实更大"的断言都无从下手，
#   而且 QFontMetrics 量出来的也是错的，行高自适应会跟着错。
EXIT_TAG_PT = 11.5       # 编号字号（正文 9pt → 明显大一号）
EXIT_TAG_QSS = """
QLineEdit#ExitTag {
    border: 1px solid transparent; background: transparent;
    color: #1f2937; padding: 1px 3px; border-radius: 6px;
}
QLineEdit#ExitTag:hover { border-color: #dfe3e8; background: #f2f4f7; }
QLineEdit#ExitTag:focus { border-color: #1976d2; background: #ffffff; }
"""

# ★ v2.7.4：只读（展示）态的样式 —— 编辑态的 hover/focus 高亮一律去掉，
#   不然鼠标一划过去就冒出边框底色，看着还是"能改的框"，误导用户。
#   只读编号仍保留大字加粗（编号是识别的锚点，要大要显眼）。
EXIT_TAG_QSS_RO = """
QLineEdit#ExitTag {
    border: 1px solid transparent; background: transparent;
    color: #1f2937; padding: 1px 3px; border-radius: 6px;
}
"""
# 只读内容：没有边框、透明底、无内边距 —— 视觉上就是一段普通文字，
# 但仍然可以拖选复制（QPlainTextEdit 只读态保留选中能力）。
EXIT_TXT_QSS_RO = """
QPlainTextEdit {
    border: none; background: transparent; padding: 0px;
}
"""

# ------------------------------------------------------------
# 一行出口怎么拆成「编号」+「内容」
# ------------------------------------------------------------
# ★★ 别想当然按"一位字母 + 出入口 + 冒号"来写。把 379 站的数据全量跑一遍，
#    有 **12 行**是别的写法，全都会掉到"内容"里 ⇒ **"出入口"三个字删不掉**：
#
#     A出入口：…                    （最常见）
#     6A号出入口：…                  黄木岗 —— 多一个"号"字
#     2a、2b出入口：… / 3a、3b、5出入口：…
#     14a、14b、14c出入口：…          大运 —— 编号长到 12 字符
#     9出入口                        福田 —— **连冒号都没有**
#     东1出入口：… / 东2出入口：…      布吉 —— 编号以**汉字**开头
#     北端出入口（连接公交车站）：…      深圳北 —— 汉字 + 括号说明
#     A1出口：… / C出口：…            永湖 —— 写的是"出口"不是"出入口"
#     E出入囗：…                     上沙 —— 官网把"口"打成了"囗"(U+56D7)
#
# 于是拆成三条正则，**按顺序**试（第一条最严，最后一条最松）：
EXIT_SUFFIX = r"(?:出入[口囗]|出口)"          # 出入口 / 出入囗 / 出口
# ① 主形态：编号是 字母·数字·顿号·逗号·斜杠·连字符
EXIT_ROW_RE = re.compile(
    r"^(([A-Za-z0-9、，,/\-]{1,14})\s*号?\s*%s)\s*[：:]?\s*(.*)$" % EXIT_SUFFIX)
# ② 汉字编号（东1 / 北端…）：★ 必须限死 ≤4 个字，否则一句普通的话
#    "本站共4个出入口，…" 会把"本站共4个"整个当成编号（5 字 ⇒ 匹配不上，安全）。
_EXIT_TAG_CN = r"[\u4e00-\u9fffA-Za-z0-9、，,/\-]"
EXIT_ROW_RE_CN = re.compile(
    r"^((%s{1,4})\s*号?\s*%s)\s*[：:]?\s*(.*)$" % (_EXIT_TAG_CN, EXIT_SUFFIX))
# ③ 兜底：`A1：xxx` 这种没写出入口字样的老写法
EXIT_ROW_RE2 = re.compile(
    r"^([A-Za-z0-9、，,/\-]{1,14})\s*号?\s*[：:]\s*(.*)$")
EXIT_ROW_RES = (EXIT_ROW_RE, EXIT_ROW_RE_CN, EXIT_ROW_RE2)

# 编号输入上限。★ 必须 ≥ 数据里最长的编号（`14a、14b、14c` 12 字符），
#   卡小了会把已有编号**截断**，一保存就把数据改坏。
EXIT_TAG_MAX_CHARS = 20
EXIT_TAG_MAX_W = 120       # 编号列宽上限（12 字符的编号 ≈ 90px）

# ★ v2.7.5：编号不再是无边框的输入框，改成**真正的按钮**。
#   用户原话：「出入口新的这些 A、B、C 作为按钮，点击后可以输入进行编辑」。
#   观感要求 = 平时看着是个圆角小按钮，点一下才变成输入框让你改编号。
EXIT_TAG_BTN_QSS = """
QPushButton#ExitTagBtn {
    border: 1px solid #c3d0de; border-radius: 9px;
    background: #f2f7fc; color: #1f2937; padding: 3px 8px;
}
QPushButton#ExitTagBtn:hover { background: #e3eefa; border-color: #1976d2;
    color: #1976d2; }
QPushButton#ExitTagBtn:pressed { background: #d6e6f7; }
"""
EXIT_TAG_ED_QSS = """
QLineEdit#ExitTagEd {
    border: 1px solid #1976d2; border-radius: 9px;
    background: #ffffff; color: #1f2937; padding: 3px 8px;
}
"""


class ExitTagChip(QStackedWidget):
    """编号「按钮」：平时是圆角小按钮（A / B / C…），**点一下就地变成输入框**。

    ★ 为什么不再用无边框 QLineEdit：
      用户原话「这些 A、B、C 作为按钮，点击后可以输入进行编辑」——
      要的是"看着是按钮、点了才能改"，不是"一进去就是个等着打字的框"。

    ★★ 对外**只暴露 `text()` / `setText()`**，所以 `ExitsEditor.rows` 的形状
      一行都不用改（`rows[i][0].text()` 在编辑弹窗、回归脚本里都在用）。
      内部 [0]=QPushButton（展示） / [1]=QLineEdit（编辑） 两页切换。

    · 点击按钮 → 切到输入框、全选现有文字，直接打字就能改；
    · 回车 / 点到别处 → 收起成按钮（文字同步到按钮上）；
    · Esc → **放弃**这一次的改动，退回点按钮之前的编号；
    · 编号清空 → 按钮显示浅色的「编号」占位字，而不是变成一块空白。
    """

    PLACEHOLDER = "编号"

    def __init__(self, text: str = "", parent=None, readonly: bool = False):
        super().__init__(parent)
        self.setObjectName("ExitTagChip")
        self.readonly = bool(readonly)
        self._bak = str(text or "")

        f = QFont()
        f.setPointSizeF(EXIT_TAG_PT)
        f.setBold(True)

        # ① 展示页：按钮
        self.btn = QPushButton(str(text or "") or self.PLACEHOLDER)
        self.btn.setObjectName("ExitTagBtn")
        self.btn.setStyleSheet(EXIT_TAG_BTN_QSS)
        self.btn.setFont(f)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # ② 编辑页：输入框（只在点过按钮之后才露出来）
        self.ed = QLineEdit(str(text or ""))
        self.ed.setObjectName("ExitTagEd")
        self.ed.setStyleSheet(EXIT_TAG_ED_QSS)
        self.ed.setFont(f)
        self.ed.setMaxLength(EXIT_TAG_MAX_CHARS)
        self.ed.setPlaceholderText(self.PLACEHOLDER)
        self.ed.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.ed.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.addWidget(self.btn)
        self.addWidget(self.ed)
        self.setCurrentIndex(0)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.btn.clicked.connect(self.begin_edit)
        self.ed.editingFinished.connect(self.end_edit)
        self.ed.returnPressed.connect(self.end_edit)
        self.ed.installEventFilter(self)

    # ------------------------------------------------------------ 对外接口
    def text(self) -> str:
        return self.ed.text()

    def setText(self, s: str) -> None:
        self.ed.setText(str(s or ""))
        self._sync_btn()

    def setReadOnly(self, on: bool) -> None:
        """只读态：仍显示成按钮，但点了不进编辑。"""
        self.readonly = bool(on)

    def setFixedWidth(self, w: int) -> None:
        super().setFixedWidth(int(w))

    def _sync_btn(self) -> None:
        t = self.ed.text().strip()
        self.btn.setText(t or self.PLACEHOLDER)

    # ------------------------------------------------------------ 两态切换
    def begin_edit(self) -> None:
        if self.readonly:
            return
        self._bak = self.ed.text()
        self.setCurrentIndex(1)
        self.ed.setFocus()
        self.ed.selectAll()

    def end_edit(self) -> None:
        if self.currentIndex() == 1:
            self._sync_btn()
            self.setCurrentIndex(0)

    def eventFilter(self, obj, ev) -> bool:
        # Esc = 放弃本次编辑（不然改错了只能手动把原编号再打一遍）
        if obj is self.ed and ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.ed.setText(self._bak)
            self.end_edit()
            return True
        return super().eventFilter(obj, ev)


class ExitsEditor(QWidget):
    """出入口的两栏编辑器：每行 = [编号按钮(A/B/C…)] + [详细信息输入框]。

    对外接口：
        `rows`  —— [(编号编辑框, 内容编辑框, 原编号, 原内容, 原行), ...]
                   （**与 v2.6.3 起 EditDialog._exit_rows 的结构完全一致**，
                     回归测试直接读它，所以别改形状）
        `text()`—— 拼回存储格式
        `add_row()` —— 追加一个空行
    """

    def __init__(self, value="", parent=None, readonly: bool = False):
        """`readonly=True` ⇒ **只读展示**（v2.7.4）。

        用户原话：「你搞丢了不同出入口外的信息」→「只恢复**能看**」。
        只读模式下：
          · 编号 / 内容都 `setReadOnly(True)`，去掉 hover/focus 的输入框外观
            （看起来就是一段文字，不再像"等着你打字"的框）；
          · **不建「＋ 添加出入口」按钮**（只读就不该能加行）；
          · 空数据时显示一句"暂无"提示，而不是留一格空白让人以为坏了。
        ★ 行高自适应（`relayout_rows`）照常跑 —— 只读也一样要"全部露出来"。
        ★ 另有一道保险在数据层：`schema.READONLY_UI_FIELDS` 让 `_collect()`
          跳过这个键，保存时 payload 里根本没有它 ⇒ 原值一个字节都不会被改。
        """
        super().__init__(parent)
        self.setObjectName("ExitsEditor")
        self.rows: List[tuple] = []      # 见类文档注释
        self._queued = False
        self.readonly = bool(readonly)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self._v = v
        # ★★ v2.7.11：末尾先挂一个**吸收余高的弹簧**，之后所有行 / 按钮都
        #   `insertWidget(count()-1)` 插到它前面。
        #   病根：右侧面板的表单在 QScrollArea 里被 `widgetResizable` 拉到视口高，
        #   多出来的高度按行分配 —— 只有一个出口时空站时，这一行会被撑到 260px，
        #   于是"编号+输入框"被推到中间、按钮沉到底，中间空出一大截
        #   （用户截图原话：「不需要留这么大的间距」）。
        #   有了这个弹簧，余高全落在最后，控件永远贴着顶部往下排。
        v.addStretch(1)

        def add_widget(w, *a):
            """插到弹簧**之前**（保证排队顺序不变）。"""
            v.insertWidget(max(0, v.count() - 1), w, *a)

        self._add_widget = add_widget

        rows = self._parse(value)
        if not rows and self.readonly:
            # 只读且没数据 ⇒ 给一句实话，别留空白
            hint = QLabel("（暂无出入口信息）")
            hint.setStyleSheet("color:#9aa4b2;font-size:12px;")
            add_widget(hint, 0, Qt.AlignLeft)
            self._empty_hint = hint
            self._add_btn = None
            return
        if not rows:
            rows = [("", "", "", "")]              # 至少给一行，否则空站没法补
        # ★ 编号列宽要**整块统一取最宽的那个**：
        #   各行自己算自己的宽度的话，编号短的行内容列会往左缩 ——
        #   一列内容左边缘参差不齐，看起来像没对齐。
        #   （`14a、14b、14c` 这种 12 字符编号实测要 ~90px，光靠常量 46 会显示不全）
        tag_w = self.calc_tag_width([r[0] for r in rows])
        for tag, txt, prefix, line in rows:
            add_widget(self._make_row(tag, txt, prefix, line, tag_w))

        if self.readonly:
            # 只读：不提供"添加一行"
            self._add_btn = None
            return

        # ＋ 添加一行：官网没数据的站要靠它补，用户自己加出口也需要
        add = QPushButton("＋ 添加出入口")
        add.setCursor(Qt.PointingHandCursor)
        # ★ 必须显式给最小高度：这条虚线按钮的样式表去掉了 DIALOG_QSS 里
        #   `padding: 6px 18px`，只剩 4px → 实测被压成 ~22px，文字上下都贴边。
        add.setMinimumHeight(28)
        add.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        add.setStyleSheet(
            "QPushButton{border:1px dashed #b9c0cb;border-radius:8px;"
            "background:transparent;color:#1976d2;padding:5px 14px;font-size:12px;}"
            "QPushButton:hover{background:#eff6ff;border-color:#1976d2;}")
        add.clicked.connect(self.add_row)
        add_widget(add, 0, Qt.AlignLeft)
        self._add_btn = add

    # ------------------------------------------------------------ 解析
    @staticmethod
    def parse_line(s: str):
        """一行 → (编号, 内容, 原样前缀)；拆不动就 ("" , 整行 , "")。"""
        for rx in EXIT_ROW_RES:
            m = rx.match(s)
            if not m:
                continue
            if rx is EXIT_ROW_RE2:               # ③ 没有"出入口"字样，整段就是编号
                return m.group(1).strip(), m.group(2).strip(), m.group(1).strip()
            # ①②  第 1 组 = 原样前缀（含"出入口"），第 2 组 = 编号
            return m.group(2).strip(), m.group(3).strip(), m.group(1).strip()
        return "", s, ""

    @classmethod
    def _parse(cls, text) -> List[tuple]:
        """把存储的多行文本解析成 [(编号, 内容, 原样前缀, 原行), ...]。"""
        rows = []
        for ln in str(text or "").splitlines():
            s = ln.strip()
            if not s:
                continue
            tag, txt, prefix = cls.parse_line(s)
            rows.append((tag, txt, prefix, s))
        return rows

    # ------------------------------------------------------------ 造行
    @staticmethod
    def calc_tag_width(tags: List[str]) -> int:
        """按最宽的编号算编号列宽度（用 QFontMetrics 量，别按字数估）。"""
        f = QFont()
        f.setPointSizeF(EXIT_TAG_PT)
        f.setBold(True)
        fm = QFontMetrics(f)
        widest = max([fm.horizontalAdvance(t or "") for t in tags] + [0])
        # ★★ v2.7.11：右侧留白 10 → **20**。原来看起来只差一点点，实测"13-15"
        #   这种 5 字符编号在岗厦北会被切成"13-1…"（用户原话「适当调整如
        #   『13-15』的输入框长度…务必显示完整」）。
        #   为什么 10 会不够：编号按钮是带圆角的按钮，文字两侧各有 QSS 的
        #   内边距；`horizontalAdvance` 量的是**字宽**，量不到那圈内边距
        #   （实测「13-15」字宽 75px，按钮要 93px 才不截断 ⇒ 需要 ~18px）。
        return int(max(EXIT_TAG_W, min(EXIT_TAG_MAX_W, widest + 20)))

    @staticmethod
    def placeholder_width() -> int:
        """**空编号行**用的最小宽度 —— 够把占位文字「编号」放成一行（v2.7.11）。

        ★ 为什么单独给空行放宽：A/B/C 那种短编号用 EXIT_TAG_W=37（用户要的
          "80% 长度"）就对；但空行的占位文字是两个汉字，11.5pt 加粗 ≈ 26px
          + 内边距 ≈ 46px ⇒ 37px 装不下，会被折成上下两行（用户截图里就是
          那个样子）。空行只有它自己，放宽不影响任何列对齐。
        """
        f = QFont()
        f.setPointSizeF(EXIT_TAG_PT)
        f.setBold(True)
        need = QFontMetrics(f).horizontalAdvance(ExitTagChip.PLACEHOLDER) + 20
        return int(max(EXIT_TAG_W, need))

    def _make_row(self, tag: str, txt: str,
                  orig_prefix: str = "", orig_line: str = "",
                  tag_w: int = None) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        # ① 编号：**按钮**（v2.7.5）—— 平时是个圆角小按钮，点一下就地变成
        #    输入框改编号；Esc 放弃、回车/点别处收起。字号加粗大一号由
        #    `ExitTagChip` 自己用 QFont 设（样式表里的 font-size 不会反映到
        #    `font()`，QFontMetrics 会量错 —— 见 EXIT_TAG_PT 的注释）。
        tag_ed = ExitTagChip(tag, readonly=self.readonly)
        _w = int(tag_w or EXIT_TAG_W)
        if not str(tag or "").strip():
            # ★ v2.7.11：空编号行放宽到"编号"两个字放得下（见 placeholder_width）
            _w = max(_w, self.placeholder_width())
        tag_ed.setFixedWidth(_w)
        # ★ 编号列宽上限必须 ≥ 数据里最长的编号（`14a、14b、14c` 12 字符 ≈ 90px），
        #   卡小了会把已有编号**截断**，一保存就把数据改坏了（见 calc_tag_width）。

        # ② 内容：宽度自适应，高度按文本量算（见 _relayout_rows）
        txt_ed = QPlainTextEdit()
        txt_ed.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        txt_ed.setPlainText(txt)
        txt_ed.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        txt_ed.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if self.readonly:
            # ★ v2.7.4：只读展示 —— 去掉输入框外观，变成一段文字。
            #   设了 QSS 就不能再调 setFrame（QSS 的 border 优先），
            #   这里只用 QSS 表达"无边框 / 透明底"。
            txt_ed.setReadOnly(True)
            txt_ed.setStyleSheet(EXIT_TXT_QSS_RO)
        else:
            txt_ed.setPlaceholderText("出口可到达的道路 / 地点，例：龙岗大道南侧、…")

        # ★ v2.6.8：编号框**垂直居中**（原来是 AlignTop，编号贴在框顶，
        #   内容一换行就变成"编号浮在上面"。用户原话：「A、B、C、D 这类文字
        #   要恰好在输入框的中间位置」）。QLineEdit 内部自己是 AlignVCenter，
        #   这里说的是**整行里**的位置。
        h.addWidget(tag_ed, 0, Qt.AlignVCenter)
        h.addWidget(txt_ed, 1)
        # 记下"原编号 / 原内容 / 原行" —— 见 `text()`：
        # 只要用户没动这一行，保存时就**原样吐回去**，一个字节都不改。
        self.rows.append((tag_ed, txt_ed, tag, txt, orig_line))
        return row

    def add_row(self) -> None:
        # ★ v2.7.4：只读展示态不允许加行（按钮本来也不建，这里再兜一道）
        if getattr(self, "readonly", False):
            return
        # 新行的编号列宽跟已有行保持一致（不然一列内容左边缘会参差）
        tag_w = self.calc_tag_width([r[0].text() for r in self.rows])
        self._v.insertWidget(max(0, self._v.count() - 1),
                             self._make_row("", "", tag_w=tag_w))
        self._schedule_relayout()

    # ------------------------------------------------------------ 行高
    def _schedule_relayout(self) -> None:
        """排队重算行高（合并同帧内的重复请求）。"""
        if self._queued:
            return
        self._queued = True

        def run():
            self._queued = False
            self.relayout_rows()

        QTimer.singleShot(0, run)

    def resizeEvent(self, ev) -> None:
        """宽度一变就重算行高（v2.7.9）。

        ★ 为什么必须挂 resize：`relayout_rows` 排队跑的那一次（构造 / 加行）
          往往还在**布局没定型**的时候 —— 那时 `viewport().width()` 只有几十像素，
          "刚好装下当前文字"就会把「宝安大道」这 4 个字折成 5 行，
          实测每个框被撑到 **70px**（≈5 行），用户看到的就是
          「你自己看都多少行了」。而宽度稳定后**再没有第二次重算**，
          这个错高度就一直挂在屏幕上。
          ⇒ 宽度一变（含第一次拿到真实宽度）就重算一次，行高才跟着真实宽度走。
        """
        super().resizeEvent(ev)
        try:
            new_w = int(self.width())
        except Exception:
            return
        if int(getattr(self, "_last_w", -1)) != new_w:
            self._last_w = new_w
            self._schedule_relayout()

    def relayout_rows(self) -> None:
        """按**当前可用宽度**给每个出口的内容框定高（内容全露出来，不出现内部滚动条）。

        ★ 为什么不能用固定高度：出口内容长短差很多（短的"宝安大道"4 字，
          长的"宝安大道西侧、福围儿童公园、宝安海事局、深圳市公安局交通管理支队机场大队"
          30+ 字），固定 1 行高的框长内容就看不见，固定 3 行高则短内容大片空白。
        ★ 为什么不能只在构造时算一次：那时布局还没定型，`viewport().width()`
          是默认值 100，算出来的行高完全是错的。
        ★ 文字换行后的真实高度只能问 QTextDocument —— 自己按字数估一定翻车。
        ★ v2.6.8：这段计算搬到了 `ui/autofit.py::fit_height`（编辑弹窗、右侧面板、
          出入口三处共用一份，"刚好全部显示完"只有一个标准）。
        """
        for row in self.rows:
            txt_ed = row[1]
            try:
                txt_ed.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                txt_ed.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                # ★ v2.7.7：最小高度由"1 行（32px）"改成**至少 2 行** ——
                #   用户原话「右侧弹窗的高度要自适应，高度至少显示 2 行」。
                #   用 `min_height_for_lines` 按当前字号实算，不写死像素
                #   （字号跟着整体缩放变，写死会在小字号下空一大截）。
                fit_height(txt_ed, min_height_for_lines(txt_ed, 2))
            except Exception:
                pass

    # ------------------------------------------------------------ 拼回
    def text(self) -> str:
        """把两栏拼回存储格式（**格式不变**，379 站数据不用迁移）。

        ★ 关键设计：**没动过的行原样吐回**。
          为什么不能一律"编号 + '出入口' + '：' + 内容"地重拼 —— 真实数据里有
          `6A号出入口`（多了个"号"）、`A1出口`（写的是"出口"）、
          `E出入囗`（官网错别字）、`9出入口`（连冒号都没有）这些写法。
          一律重拼就等于：**用户打开弹窗、什么都没改、点保存，
          12 行数据被悄悄改写**。所以按"有没有动过"分两条路。
        """
        parts = []
        for tag_ed, txt_ed, orig_tag, orig_txt, orig_line in self.rows:
            tag = tag_ed.text().strip()
            txt = txt_ed.toPlainText().strip()
            if not tag and not txt:
                continue                            # 空行（含用户加了又没填的）丢掉
            if orig_line and tag == orig_tag and txt == orig_txt:
                parts.append(orig_line)             # ← 一字未动，原样保留
                continue
            if tag:
                parts.append("%s出入口：%s" % (tag, txt))
            else:
                parts.append(txt)
        return "\n".join(parts)
