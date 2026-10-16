"""
ui/timetable_editor.py
==============================
「首/末班车」字段的专用编辑器（v2.6.4）。

为什么单独做而不是继续用一个大文本框：
用户原话「首/末班车看起来很不明显」——原来存进去的是这样的纯文本：

    工作日 · 1号线：往罗湖 首06:02 末23:47；往机场东 首06:41 末23:21
    工作日 · 7号线：往深大丽湖 首06:30 末23:35；往太安 首05:42 末23:26
    休息日 · 1号线：…

一行的信息量 ≈ 「日期类型 + 线路 + 2 个方向 × (首班 + 末班)」= **9 个字段**，
全挤成一行灰色小字，扫一眼根本抓不到想要的那个时间。

现在改成**分块 + 列对齐的表格**：

    ●工作日                                    ← 彩色胶囊（蓝/绿/橙）
      1号线   往罗湖      06:02  →  23:47      ← 首班蓝药丸 / 末班红药丸，加粗大一号
               往机场东    06:41  →  23:21
      7号线   往深大丽湖  06:30  →  23:35
               往太安      05:42  →  23:26
    ●休息日
      …

★ 存储格式**一行都没改**（仍是 `工作日 · 1号线：往…`），只在显示层结构化
  → 379 站的数据不用迁移，导入脚本也不用改。

★★ 和出入口编辑器（ui/edit_dialog.py::_collect_exits）同一个铁律：
   **没动过的行必须原样吐回**。真实数据里有 `首-- 末--`（终点站没有反向班次）
   这类非标准值，保存时如果一律按模板重拼就会被改写 ——
   用户打开弹窗什么都没改、点一下保存，数据就悄悄变了。

★★ 新增行要走 `_build_ui()`（按现有模型重建），**不能**走 `set_text(self.text())`
   —— 后者会重新解析一遍，未填内容的新行会被当空行丢掉（表现为"点了＋没反应"）。
"""

from __future__ import annotations

import re
from typing import Dict, List

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import (
    QFont, QFontMetrics, QColor, QPainter, QPolygonF, QPen,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QLineEdit, QPushButton, QSizePolicy, QFrame, QStyledItemDelegate,
    QStyleOptionViewItem,
)

from core.data_manager import get_data_manager


FONT_FAMILY = "Microsoft YaHei"

# ---------------- 日期类型：给个颜色，一眼分开三种班次 ----------------
TT_DATE_STYLE: Dict[str, tuple] = {
    "工作日": ("#E3F2FD", "#1565C0"),     # 浅蓝底 + 深蓝字
    "休息日": ("#E8F5E9", "#2E7D32"),     # 浅绿底 + 深绿字
    "节假日": ("#FFF3E0", "#EF6C00"),     # 浅橙底 + 深橙字
}
TT_DATE_FALLBACK = ("#EEF2F7", "#475569")   # 数据里出现别的类型时兜底

# ---------------- 列宽（固定值 ⇒ 各分组天然对齐）----------------
# ★ v2.6.11：**没有"圆点列"了**。原来每行线路前面那个线路色小圆点占一列
#   （16px + 8px 列间距），用户要求「工作日下拉和右侧『线路』挨得更近」，
#   这段就是挡在中间的 24px。
# ★ v2.6.16：颜色信息从"表头下方一条色块条"改成**画在字上**
#   —— 线路名那一格的外圈就是这条线的官方色（`_apply_line_ring`），
#     既省掉一整行高度，指认关系也更直接（不用去对图例）。
COL_LINE = 92
COL_DIR = 150
COL_TIME = 68
COL_ARROW = 20
GAP_COL = 8

# ---------------- 紧凑模式（v2.6.5：右侧信息面板用）----------------
# 面板可用宽实测只有 **338px**，而完整表格最少要
#   16+92+150+68+20+68 + 5×8 = **454px** —— 直接塞进去一定横向溢出。
# 紧凑模式做两件事：①列间距减半、首末/箭头列收窄；
#                 ②「线路」「方向」两列按**全量站点**实测（见 `global_col_widths`，
#                    v2.6.12 起不再是"按当前站实测" —— 那会让切站时列宽跳 22px）。
COMPACT_DOT = 14
# ★★ v2.7.4：时间列宽度**不再写死**，改成"按当前字号实测 + 内耗 + 呼吸"现算
#   （见 `_compute_cols` 里的 `_time_need()`）。
#   · v2.6.12 写死 54 的理由是"面板可用宽只有 356、再宽就横向溢出"，
#     当时验算的是「'23:59' 文字 33px + 内耗 16px = 49px，还剩 5px」。
#   · ★ 但那个 33px 是**旧字号**下的度量。TT_TIME_PT 后来调大到 11.5 粗体，
#     实测 `06:25` / `23:59` 已经是 **41px** ⇒ 41 + 16 = 57 > 54，
#     时间药丸是**居中对齐**（AlignHCenter）⇒ 左右各被裁 1~2px。
#     用户原话：「首班、末班下面的第一个数字和颜色块最左侧没显示全」
#     —— 裁掉的正是最左边那个数字的左半边和药丸色块的左边缘。
#   · 现在：面板最小宽已放宽到 480（可用 ~478），紧凑表 hint 才 290，
#     时间列加宽到 ~63 完全放得下，不必再抠这 8px。
COMPACT_TIME = 54        # 下限（真正取值由 _time_need() 决定，见 _compute_cols）
COMPACT_ARROW = 16
COMPACT_GAP = 4
# 时间药丸的"文字之外"要占的横向像素：QSS `padding: 2px 5px`（左右各 5）
# + `border: 1px`（左右各 1）+ 再留 8px 呼吸 ⇒ **20px**。
TIME_W_CHROME = 20
# 实测列宽的取值区间（下限保证不挤、上限防止一条异常长的线路名把表格撑爆）
LINE_W_RANGE = (56, 92)
DIR_W_RANGE = (90, 150)
COMPACT_LINE_W_RANGE = (42, 66)
COMPACT_DIR_W_RANGE = (62, 100)
LINE_W_PAD = 10          # 实测宽度之外再留一点呼吸
DIR_W_PAD = 12

# ---------------- 字号 ----------------
# ★ 字号/字重一律用 **QFont** 设，不用样式表 —— 样式表里的 font-size
#   不会反映到 widget.font()（pointSizeF() 返回 −1），断言和字体度量全失效。
TT_TEXT_PT = 9.0        # 方向、线路名等普通文字
TT_TIME_PT = 11.5       # 首/末班时间：**明显大一号**（这是"看得明显"的关键）

# ---------------- 表头（v2.6.7）----------------
# ★★ 表头必须**黑色加粗**，而且每个表头格子要与下方内容**等宽** ——
#    实测踩过：表头 QLabel 只有"线路"两个字的自然宽度（22px），
#    下方输入框却是定宽（56/90/68px），两边都靠左放 ⇒ 左边缘齐而**中心差
#    (内容宽 − 标签宽) / 2**（实测 17 / 34 / 23px），看着就是歪的。
#    所以表头一律 `setFixedWidth(列宽)` + `AlignCenter`，下方也同样居中。
TT_HEADER_PT = 9.0
TT_HEADER_COLOR = "#000000"     # 用户要求"黑色"

# ---------------- 日期类型下拉（v2.6.7 加，v2.6.8 居中 + 挪到表头行）----------------
# ★★ QComboBox **没有** `text-align` 这种样式表属性，收起态那行文字由
#    `QStyle` 画（CE_ComboBoxLabel），默认靠左。
#    （改 item delegate 只影响**展开后的列表**，对收起那一格没用。）
# ★★★ v2.6.8 走过的一段弯路（v2.6.9 已回退，留作警示）：
#    为了居中用了 `setEditable(True)` + 内部 QLineEdit `setAlignment(AlignCenter)`
#    + `setReadOnly(True)`（防止当搜索框乱打字）。副作用是致命的：
#    **editable 的下拉把鼠标事件交给内部输入框，QComboBox 只在点箭头时才弹列表**，
#    再叠上只读 ⇒ 点文字区域毫无反应 —— 用户原话「此下拉菜单无法点击」。
#    ★ 结论：**不要用 editable 换居中**。正确解是回到**不可编辑**（点击行为
#      完全交给 Qt 原生，整块都能点开），收起态那一格自己画（见 `_DateCombo`）。
# ★★ v2.6.15：下拉**并进了网格第 0 列**（不再是"网格外面的一段缩进"）。
#    它所在的那一列内容行放的是**线路名** ⇒ 用户要的"『一号线』落在
#    『工作日』正下方"自然成立，「线路」这个表头文字也随之删掉。
#    ★ 历史坑（v2.6.7）：当年下拉在网格外面，只给表头加缩进、不给内容行加
#      ⇒ 表头被整体顶偏（实测 **116px**），"表头与内容中心对齐"当场破功。
#      并进网格后这类"两处缩进要一致"的问题**从根上消失了** ——
#      两边共用同一套 `self.COLS`。
TT_COMBO_H = 26
# ★★ v2.6.9：宽度按"**总宽 = 最长选项文字宽 + 箭头区×2 + 边距×2**"算。
#    "箭头区×2"是关键：文字是相对**整颗胶囊**居中的，右边要留出一个箭头区，
#    左边就必须留出**同样宽**的一个，否则文字看着就是偏右的（不是真居中）。
#    v2.6.8 的坑：宽度按"内耗 32px"算，样式表却写了 `padding:2px 10px`(20)
#    + `drop-down width:16px` + 输入框 `padding:0 2px`(4) = **40px**，
#    于是"工作日"(≈36~39px) 在 58~71px 宽的下拉里只剩 14~27px ⇒ 只露出"工"。
#    ★ 判据（回归里直接断言）：`_combo_w() - combo_chrome() >= 文字宽`，
#      且 `combo_chrome() >= 2 × 箭头区`（保证居中文字不撞箭头）。
# 紧凑档（右侧面板，可用宽只有 **356px**）：
#   实测预算：表格本体 290px（14+52+72+58+16+58 + 5×4），留给下拉+间隔只剩
#   **66px** ⇒ 下拉最多 64px、间隔 2px。放宽任何一个都会让面板横向溢出。
# ★ gap（下拉与右侧表格的间距）**取 0**：用户要"挨得近一些"。再往下压就只剩
#   圆点列(16px) + 网格列间距(8px) 这两样结构性尺寸了 —— 它们一动，
#   表头就会和下方内容错开（v2.6.7 刚修好的"表头与内容中心对齐"会破功）。
TT_COMBO_METRIC = {
    False: dict(pt=9.5, arrow=14, edge=2, lo=64, hi=110, gap=0),
    True:  dict(pt=9.0, arrow=10, edge=2, lo=48, hi=64,  gap=0),
}

QSS_BASE = """
QLineEdit#TT {
    border: 1px solid transparent; background: transparent;
    border-radius: 6px; padding: 2px 5px;
}
QLineEdit#TT:hover { border-color: #dfe3e8; background: #f5f7fa; }
QLineEdit#TT:focus { border-color: #1976d2; background: #ffffff; }
"""
# 首班 / 末班做成两颗不同颜色的"药丸"，一眼分得开 ——
# 这是"看到 06:02 就知道是首班"的关键。
QSS_FIRST = """
QLineEdit#TTFirst {
    border: 1px solid transparent; background: #E7F1FE; color: #1565C0;
    border-radius: 8px; padding: 2px 5px; font-weight: 700;
}
QLineEdit#TTFirst:hover { background: #D6E7FD; }
QLineEdit#TTFirst:focus { border-color: #1976d2; background: #ffffff; }
"""
QSS_LAST = """
QLineEdit#TTLast {
    border: 1px solid transparent; background: #FDECEA; color: #C62828;
    border-radius: 8px; padding: 2px 5px; font-weight: 700;
}
QLineEdit#TTLast:hover { background: #FBD9D5; }
QLineEdit#TTLast:focus { border-color: #1976d2; background: #ffffff; }
"""

_HEAD_RE = re.compile(r"^([^·•]{1,8}?)\s*[·•]\s*(.+)$")
_LINE_RE = re.compile(r"^([^：:]+)[：:]\s*(.+)$")
# ★ 方向要**连着"往"一起捕获**（`(.+?)\s+首`），不要把"往"吃掉：
#   吃掉的话界面上只剩「罗湖」，拼回去又得再补一个"往"，两边很容易不相等；
#   连着捕就天然"显示什么样、存回去就什么样"。
_ITEM_RE = re.compile(r"^(.+?)\s+首\s*(\S+)\s+末\s*(\S+)$")


def _mk_line(object_name: str, text: str, extra_qss: str = "",
             pt: float = TT_TEXT_PT, bold: bool = False) -> QLineEdit:
    """造一个"画成标签样子"的输入框（默认无边框，hover/focus 才显出来）。"""
    ed = QLineEdit(text)
    ed.setObjectName(object_name)
    ed.setStyleSheet(QSS_BASE + extra_qss)
    f = QFont(FONT_FAMILY)
    f.setPointSizeF(pt)
    f.setBold(bold)
    ed.setFont(f)
    ed.setFrame(False)
    return ed


class _CenterDelegate(QStyledItemDelegate):
    """让**展开后的下拉列表**每一项文字都居中（v2.6.8）。

    ★ 为什么必须写这个：`setItemData(..., Qt.TextAlignmentRole)` 只对
      `QStyledItemDelegate` 有效，而 QComboBox 内部用的是 `QItemDelegate`
      —— 走 role 那条路在本机实测**不生效**。直接在 paint 前改
      `option.displayAlignment` 是唯一稳的做法。
    """

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        opt.displayAlignment = Qt.AlignCenter
        super().paint(painter, opt, index)


class _DateCombo(QComboBox):
    """日期类型下拉：**不可编辑** + 收起态自绘（居中文字 + 右侧三角）。

    ★★ 为什么自绘（v2.6.9）：
      · QComboBox 没有 `text-align`，收起那一行默认靠左 —— 用户要**居中**；
      · 唯一能居中的"官方"路子是 `setEditable(True)`，但那会把鼠标事件
        交给内部 QLineEdit ⇒ 只有点箭头才弹列表 ⇒ 用户报「无法点击」；
      · 所以：**保持不可编辑**（点击行为回归 Qt 原生，整块都能点开），
        收起态这一格自己用 QPainter 画：胶囊底 + 居中文字 + 右侧三角。
    ★ 不可编辑 ⇒ 用户也不可能在里面乱打字（比 readOnly 更彻底）。
    ★ 展开后的列表仍走 `_CenterDelegate`（paint 里改 displayAlignment）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TTDateCombo")
        self._bg = TT_DATE_FALLBACK[0]
        self._fg = TT_DATE_FALLBACK[1]
        self._arrow = 14
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.view().setItemDelegate(_CenterDelegate(self))
        self.setStyleSheet(
            "QComboBox#TTDateCombo QAbstractItemView{background:#ffffff;"
            "selection-background:#EFF6FF;}")

    def set_date_style(self, bg: str, fg: str, arrow: int) -> None:
        if (bg, fg, arrow) != (self._bg, self._fg, self._arrow):
            self._bg, self._fg, self._arrow = bg, fg, int(arrow)
            self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = min(r.height() / 2.0, 13.0)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._bg))
        p.drawRoundedRect(r, rad, rad)
        if self.underMouse():                       # 悬停时给一圈同色描边
            pen = QPen(QColor(self._fg))
            pen.setWidthF(1.0)
            pen.setColor(QColor(self._fg))
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, rad, rad)
            p.setPen(Qt.NoPen)
        # ★ 文字相对**整颗胶囊**居中（不是"去掉箭头后居中"）        # 宽度按
        #   `文字宽 + 箭头区×2 + 边距×2` 算 ⇒ 居中后左右各留出 ≥ 一个箭头区。
        p.setPen(QColor(self._fg))
        p.setFont(self.font())
        p.drawText(QRectF(self.rect()), Qt.AlignCenter, self.currentText())
        # 右侧三角（下箭头）
        aw = float(self._arrow)
        cx = self.width() - aw * 0.5 - 1.0
        cy = self.height() * 0.5
        s = 3.1
        p.setBrush(QColor(self._fg))
        p.drawPolygon(QPolygonF([
            QPointF(cx - s, cy - s * 0.55),
            QPointF(cx + s, cy - s * 0.55),
            QPointF(cx, cy + s * 0.72),
        ]))
        p.end()


class _LineRow:
    """一条线路的行组：`1号线：往A 首… 末…；往B 首… 末…`"""

    def __init__(self, line: str, items: List[tuple], raw: str = ""):
        self.orig_line = raw           # 原始整行（用于"没动过就原样吐回"）
        self.orig_line_name = line
        self.orig_items = items        # [(dir, first, last), ...]
        self.keep = False              # True = 用户新增的行（空也不许丢）
        self.line_ed: QLineEdit = None
        self.items: List[dict] = []    # [{"dir","first","last","_*_ed"}]


class _Group:
    """同一个日期类型下连续的一组线路行。"""

    def __init__(self, date: str):
        self.date = date
        self.date_ed: QLineEdit = None
        self.rows: List[_LineRow] = []


# ★ 全量列宽缓存：{"w": (线路列原始宽, 方向列原始宽)}
#   只扫一次（379 站 1284 行，实测 **24ms**），因为右侧信息面板**每次切换站点
#   都会新建一个 TimetableEditor**，不缓存的话切一次站就要扫一次。
#   ★ 完整表 / 紧凑表共用同一份**原始**宽度，各自再夹进自己的区间里。
_GLOBAL_COL_W: Dict[str, tuple] = {}


def global_col_widths() -> tuple:
    """扫**全量站点**的首末班车，返回 (线路列需要宽, 方向列需要宽)。

    ★★ 为什么不能按**当前站**实测（v2.6.12 修掉的老问题）：
       每个站的线路名 / 方向名长度不同 ⇒ 在右侧面板里**切换站点时列宽跟着变**，
       整个表格左右抖。实测紧凑表：上塘 [44,72] → 上屋 [52,84] →
       前海湾 [52,62]，单次最多跳 **22px**。
       改成"所有站共用一份" ⇒ 列宽恒定，切站时表格纹丝不动。
    ★ 实测全量结果：最宽线路名「6号线支线」60px、最宽方向「往深圳湾口岸」72px；
       夹进区间后完整表 [70, 84]、紧凑表 [66, 84] —— 紧凑表总宽 **298px**
       仍在面板可用 338px 之内，不会撑爆。
    """
    if "w" not in _GLOBAL_COL_W:
        f_l = QFont(FONT_FAMILY)
        f_l.setPointSizeF(9.5)
        f_l.setBold(True)
        f_d = QFont(FONT_FAMILY)
        f_d.setPointSizeF(TT_TEXT_PT)
        fm_l, fm_d = QFontMetrics(f_l), QFontMetrics(f_d)
        lw = dw = 0.0
        try:
            for s in get_data_manager().all_stations().values():
                for ln in str(s.get("timetable") or "").splitlines():
                    got = TimetableEditor.parse_line(ln)
                    if not got:
                        continue
                    _date, line, items = got
                    lw = max(lw, fm_l.horizontalAdvance(line or ""))
                    for it in items:
                        dw = max(dw, fm_d.horizontalAdvance(it[0] or ""))
        except Exception:
            lw = dw = 0.0
        _GLOBAL_COL_W["w"] = (lw, dw)
    return _GLOBAL_COL_W["w"]


class TimetableEditor(QWidget):
    """首末班车的表格化编辑器。

    对外接口：`text()`（拼回存储格式）、`set_text()`、`set_readonly_groups()`。
    """

    changed = Signal()

    # v2.6.11：删掉圆点列 ⇒ 0=线路 1=方向 2=首班 3=→ 4=末班
    COLS = [COL_LINE, COL_DIR, COL_TIME, COL_ARROW, COL_TIME]

    # ================================================== 解析
    @staticmethod
    def parse_line(s: str):
        r"""`工作日 · 1号线：往罗湖 首06:02 末23:47；往机场东 首06:41 末23:21`
        → (date, line, [(dir, first, last), ...])，解析不了返回 None。

        ★ `首-- 末--`（终点站没有反向班次）是合法值：时间是 `\S+`
          而不是 `\d{2}:\d{2}`，否则 64 个终点站的行会整行落到兜底显示。
        """
        head = _HEAD_RE.match(s)
        if not head:
            return None
        date = head.group(1).strip()
        seg = _LINE_RE.match(head.group(2).strip())
        if not seg:
            return None
        line = seg.group(1).strip()
        items = []
        for it in [x.strip() for x in re.split(r"[；;]", seg.group(2))
                   if x.strip()]:
            m = _ITEM_RE.match(it)
            if not m:
                return None                 # 有任一条不规范 → 整行走兜底
            items.append((m.group(1).strip(), m.group(2).strip(),
                          m.group(3).strip()))
        if not items:
            return None
        return date, line, items

    def _parse(self, text) -> None:
        """把多行文本解析成 `self._groups` + `self._leftovers`。

        分组按"**连续**相同日期类型"切 —— 就算数据里日期类型不是严格分段也不会串组。
        """
        groups: List[_Group] = []
        leftovers: List[str] = []
        for ln in (str(text or "").replace("\r\n", "\n")
                   .replace("\r", "\n").splitlines()):
            s = ln.strip()
            if not s:
                continue
            got = self.parse_line(s)
            if got is None:
                leftovers.append(s)          # 解析不了 → 原样显示，绝不丢内容
                continue
            date, line, items = got
            if not groups or groups[-1].date != date:
                groups.append(_Group(date))
            row = _LineRow(line, items, s)
            row.items = [{"dir": d, "first": f, "last": l}
                         for d, f, l in items]
            groups[-1].rows.append(row)
        self._groups = groups
        self._leftovers = leftovers

    # ================================================== 构造
    def __init__(self, text: str = "", parent=None, compact: bool = False):
        super().__init__(parent)
        self.setObjectName("TimetableEditor")
        self._groups: List[_Group] = []
        self._leftovers: List[str] = []
        # v2.6.5：compact=True ⇒ 收窄到能塞进右侧信息面板（338px）。
        # ★ 只是**列宽不同**，解析/拼回/“原样吐回”逻辑完全共用一份。
        self.compact = compact
        self._gap = GAP_COL
        self.COLS = list(type(self).COLS)

        # v2.6.7：三种日期类型合成**一个下拉菜单**（用户要求），一次只看一种。
        # ★ 注意：分组控件**全部都建**，只是把不显示的那一组 `setVisible(False)`。
        #   绝不能"只建当前组" —— 被隐藏分组的行拿不到新控件项，
        #   旧的 `row.line_ed` 就指向已 `deleteLater()` 的 C++ 对象，
        #   `text()` 再去读它不是抛异常，是直接闪退（见 §4.16 同款坑）。
        self._cur = 0                       # 当前显示的分组下标
        self._group_boxes: List[QWidget] = []
        # ★ v2.6.8：下拉**每次重建 UI 都新建一个**，不要在 __init__ 里建好了复用。
        #   它现在是表头行的子控件，而 `_clear_ui()` 会把表头整块 `deleteLater()`；
        #   复用同一个实例 ⇒ 第二次重建时 `self.date_combo` 指向已销毁的 C++ 对象，
        #   一访问就闪退（项目里同款坑见 MEMORY §4.16）。
        self.date_combo: QComboBox = None
        self._diff_label: QLabel = None      # v2.6.10：与基准档的差异提示
        self._v = QVBoxLayout(self)
        self._v.setContentsMargins(0, 0, 0, 0)
        self._v.setSpacing(8)
        self.set_text(text)

    # ---------------- 时间列宽：按字号实测（v2.7.4）----------------
    def _time_need(self) -> int:
        """首班/末班两列各自需要的宽度 = 最长时刻文字 + 药丸内耗（`TIME_W_CHROME`）。

        ★★ 为什么必须"实测"而不是写死（v2.7.4 的账）：
          时间药丸是 `QLineEdit` + QSS `padding:2px 5px; border-radius:8px`，
          文字**居中**（AlignHCenter）。列宽一旦小于「文字宽 + 内耗」，
          居中裁剪是**左右同时发生**的 —— 用户看到的就是
          「第一个数字和色块最左侧没显示全」（原话）。
        ★ 字体必须与 `_mk_line(..., pt=TT_TIME_PT, bold=True)` **同源**，
          否则下次改字号又会重现同一个 bug。
        ★ 数据里时刻恒为 `HH:MM`（终点站没有反向班次时是 `--`），
          所以按 `23:59` 量一次就是上界；若数据里出现脏的长串，下面的
          遍历也会把它算进去，绝不裁字。
        """
        f = QFont(FONT_FAMILY)
        f.setPointSizeF(TT_TIME_PT)
        f.setBold(True)
        fm = QFontMetrics(f)
        w = fm.horizontalAdvance("23:59")
        for g in (self._groups or []):
            for row in (g.rows or []):
                for it in (row.items or []):
                    w = max(w, fm.horizontalAdvance(str(it.get("first", "") or "")))
                    w = max(w, fm.horizontalAdvance(str(it.get("last", "") or "")))
        return int(w) + TIME_W_CHROME

    # ---------------- 列宽：**全站共用一份**（v2.6.12：不再按当前站实测）----------------
    def _compute_cols(self) -> None:
        """按**全量站点**实测「线路」「方向」两列宽度（不是只看当前站）。

        ★ 同一实例里所有网格共用 `self.COLS` ⇒ 表头与各分组天然对齐；
          多余宽度由 `_prep_grid` 末尾的**拉伸列**吸收，不会被摊到各列上
          （摊到各列会让表头和分组错位，见 `_prep_grid` 的注释）。
        """
        lw, dw = global_col_widths()
        if lw <= 0 and dw <= 0:
            # ★ 兜底：全量扫描拿不到数据（比如只用合成文本跑单元测试）时，
            #   退回"按当前内容实测"的老行为，至少不会列宽为 0。
            f_l = QFont(FONT_FAMILY)
            f_l.setPointSizeF(9.5)
            f_l.setBold(True)
            f_d = QFont(FONT_FAMILY)
            f_d.setPointSizeF(TT_TEXT_PT)
            fm_l, fm_d = QFontMetrics(f_l), QFontMetrics(f_d)
            for g in (self._groups or []):
                for row in g.rows:
                    lw = max(lw, fm_l.horizontalAdvance(row.orig_line_name or ""))
                    for it in row.items:
                        dw = max(dw, fm_d.horizontalAdvance(it.get("dir", "") or ""))
        if self.compact:
            lo, hi = COMPACT_LINE_W_RANGE
            dlo, dhi = COMPACT_DIR_W_RANGE
            tm, ar, gap = COMPACT_TIME, COMPACT_ARROW, COMPACT_GAP
        else:
            lo, hi = LINE_W_RANGE
            dlo, dhi = DIR_W_RANGE
            tm, ar, gap = COL_TIME, COL_ARROW, GAP_COL
        # ★★ v2.7.4：时间列（首班/末班）按**当前字号实测**定宽。
        #   写死列宽的老账：TT_TIME_PT 调到 11.5 粗体后 `06:25` 实测 41px，
        #   而紧凑档列宽还是 54 ⇒ 41 + 内耗 16 = 57 > 54，
        #   时间药丸居中 ⇒ 左右各裁 1~2px（用户看到的"最左侧没显示全"）。
        #   这里用「本实例里最长的那条时刻」实测，再加 QSS 内耗与呼吸。
        #   ★ 取 max(写死下限, 实测) ⇒ 只可能变宽，不可能再出现裁字。
        _tm_need = self._time_need()
        tm = max(tm, _tm_need)
        lw = max(lo, min(hi, lw + LINE_W_PAD))
        dw = max(dlo, min(dhi, dw + DIR_W_PAD))
        self._gap = gap
        # ★ v2.6.15：**第 0 列要同时容下"日期类型下拉"和"线路名"**（取大者）。
        #   用户原话：「删除文字『线路』，但下方显示的内容如『一号线』放到表头
        #   如『工作日』正下方，其余表头等内容均往左挪动到合适位置」
        #   ⇒ 下拉从网格**外面**搬进**第 0 列**（线路名那一列），
        #     两者叠在同一列的上下两行，"一号线"就天然落在"工作日"正下方；
        #     原来 `[槽位][间距]` 那 73px 缩进随之消失 ⇒ 右侧各列整体左移。
        #   ★ 下拉通常比线路名宽（71 vs 70），所以列宽取 `max`；两边共用
        #     同一套 `COLS`，表头与内容行仍然严格对齐。
        col0 = max(lw, int(getattr(self, "_slot", 0) or 0))
        # ★ v2.6.11：没有圆点列了（见 COLS 处的注释）
        self.COLS = [col0, dw, tm, ar, tm]
        self._col_line, self._col_dir = col0, dw
        self._col_time, self._col_arrow = tm, ar

    # ---------------- 日期类型下拉 ----------------
    def _combo_metric(self) -> dict:
        """当前档位（完整表 / 紧凑表）的下拉尺寸参数。"""
        return TT_COMBO_METRIC[bool(self.compact)]

    @staticmethod
    def combo_chrome(m: dict) -> int:
        """下拉除文字外要占的横向像素 = 箭头区×2 + 边距×2。

        ★★ 为什么是"箭头区×**2**"：文字相对整颗胶囊居中，右边让出一个
          箭头区，左边就必须让出同样宽的一个，否则看着是偏右的（假居中）。
        ★ 这两个数必须与 `_DateCombo.paintEvent()` 里画箭头时用的
          `self._arrow`（= m["arrow"]）**同源**，否则要么撞箭头要么不居中。
        """
        return 2 * m["arrow"] + 2 * m["edge"]

    def _combo_w(self) -> int:
        """下拉的宽度：**按最长的那个日期类型实测**，不是写死一个常数。

        ★ 写死 110px 在右侧面板（可用 356px）里直接把表格撑爆
          （实测 sizeHint 406 > 356）。所以按内容量，再夹在区间里。
        ★ v2.6.9：内耗由 `combo_chrome()` 现算，与样式表同源。
        """
        names = [g.date for g in (self._groups or [])] or ["工作日"]
        m = self._combo_metric()
        f = QFont(FONT_FAMILY)
        f.setPointSizeF(m["pt"])
        f.setBold(True)
        fm = QFontMetrics(f)
        need = max(fm.horizontalAdvance(nm) for nm in names) + self.combo_chrome(m)
        return int(max(m["lo"], min(m["hi"], need)))

    def _combo_gap(self) -> int:
        """下拉与右侧表格的间距（v2.6.9：收到 2px —— 用户要"挨得近一些"）。"""
        return self._combo_metric()["gap"]

    def _combo_slot(self) -> int:
        """日期类型下拉需要的**宽度**（0 = 不显示下拉）。

        只有一种日期类型时不显示下拉 ⇒ 0（表格不用白缩进一大截）。
        ★ v2.6.15 起它直接决定**网格第 0 列**的宽度下界
          （`_compute_cols` 里取 `max(线路名宽, 本值)`）——
          下拉就在这一列的表头位置、"线路名"在同一列的内容行位置。
        ★ 这里**只返回下拉本身的宽度**，不含任何间距：列宽是纯控件宽度，
          间距由网格的 `horizontalSpacing` 统一管，混进来就会错位。
        """
        if len(self._groups or []) < 2:
            return 0
        return self._combo_w()

    def _new_combo(self) -> QComboBox:
        """造一个**文字居中**的日期类型下拉。

        ★ 居中的两段式做法（缺一段都不行）：
          · 收起态：`setEditable(True)` + 内部 QLineEdit `AlignCenter`
          · 展开态：给 view 装 `_CenterDelegate`
        """
        cb = _DateCombo()
        m = self._combo_metric()
        f_c = QFont(FONT_FAMILY)
        f_c.setPointSizeF(m["pt"])
        f_c.setBold(True)
        cb.setFont(f_c)
        cb.setFixedHeight(TT_COMBO_H)
        cb.setFixedWidth(self._combo_w())
        cb.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # ★ 不可编辑 —— 点击行为完全交给 Qt 原生（整块都能点开）。
        #   v2.6.8 为了居中改成 editable，结果点文字区域弹不出列表。
        cb.setEditable(False)
        # ★★ v2.6.10：**两条路都接上**，任何一条走到都能切换：
        #   · `currentIndexChanged[int]` —— 程序设置 / 键盘上下键走这条；
        #   · `activated[int]`           —— **用户真的从列表里点了一项**才发这条。
        #   只接前者的话，万一某个平台/焦点状态下它没发，用户就会看到
        #   "下拉能选、下面表格纹丝不动"（v2.6.9 用户原话）。
        #   ★ 显式写 `[int]`：`currentIndexChanged` 有 (int)/(str) 两个重载，
        #     不写下标时取哪一路取决于绑定版本，写死才不会踩。
        cb.currentIndexChanged[int].connect(self._on_date_changed)
        cb.activated[int].connect(self._on_date_changed)
        return cb

    def set_text(self, text: str) -> None:
        self._parse(text)
        if not self._groups and not self._leftovers:
            g = _Group("工作日")
            r = _LineRow("", [], "")
            r.items = [{"dir": "", "first": "", "last": ""}]
            g.rows.append(r)
            self._groups = [g]
        self._build_ui()

    def _clear_ui(self) -> None:
        while self._v.count():
            it = self._v.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        # ★ 必须清掉缓存引用：`deleteLater()` 之后这个 Python 壳还指着
        #   **已销毁的 C++ 对象**，下次 `_sync_diff_label()` 一访问就闪退
        #   （项目里同款坑见 §4.16）。
        self._diff_label = None

    def _sync_combo(self) -> None:
        """下拉菜单的选项 = 数据里实际存在的日期类型；顺手给每个选项上官方配色。"""
        cb = self.date_combo
        if cb is None:
            return
        names = [g.date for g in (self._groups or [])]
        cb.blockSignals(True)
        cb.clear()
        for i, nm in enumerate(names):
            cb.addItem(nm)
            _bg, fg = TT_DATE_STYLE.get(nm, TT_DATE_FALLBACK)
            cb.setItemData(i, QColor(fg), Qt.ForegroundRole)
            # 列表项居中（role 这一路在本机不是每次都生效，真正的保险是
            # `_CenterDelegate`；两条都留着，任何一条起作用就够了）
            cb.setItemData(i, int(Qt.AlignCenter), Qt.TextAlignmentRole)
        idx = min(self._cur, len(names) - 1) if names else -1
        if idx >= 0:
            cb.setCurrentIndex(idx)
        self._cur = max(0, idx)
        cb.setVisible(len(names) > 1)      # 只有一种日期类型时没必要显示
        cb.blockSignals(False)
        self._apply_combo_style()

    def _apply_combo_style(self) -> None:
        """收起时的下拉框用当前类型的配色（沿用原来那颗胶囊的视觉线索）。"""
        nm = self.current_date()
        if not nm:
            return
        _bg, fg = TT_DATE_STYLE.get(nm, TT_DATE_FALLBACK)
        m = self._combo_metric()
        # ★ 胶囊色 = 当前日期类型的官方配色（沿用原来那颗胶囊的视觉线索）。
        #   收起态是 `_DateCombo.paintEvent` 自己画的，不用样式表。
        self.date_combo.set_date_style(_bg, fg, m["arrow"])

    # ---------------- 与「基准档」的差异（v2.6.10）----------------
    # ★ 起因：用户报「下拉能选了，但首末班车数据没改变」。实测切换**是生效的**
    #   （见 `tools/_probe_v269_switch*.py`、`_probe_v269_combo_repaint.py`），
    #   真正的原因是**官方数据本身三档差别极小**：
    #     · 346 个三档齐全的站里，**86 个（24.9%）「工作日 vs 休息日」一个格子都不差**；
    #     · 32 个（9.2%）三档逐字相同（13 号线 17 站 + 4 号线 13 站）；
    #     · 99 个（28.6%）第一行完全相同。
    #   用户看一眼第一行没变，自然以为"没切换成功"。
    #   ⇒ 所以加一行**差异提示**：明确告诉他"是数据一样，不是没切过去"。
    def _times(self, g: _Group) -> List[tuple]:
        """取一组里所有的 (首班, 末班)，按行顺序（用于和基准档逐格比对）。"""
        out = []
        for row in g.rows:
            for it in row.items:
                fe = it.get("_first_ed")
                le = it.get("_last_ed")
                f = fe.text().strip() if fe is not None else it.get("first", "")
                l = le.text().strip() if le is not None else it.get("last", "")
                out.append((f, l))
        return out

    def _diff_vs_base(self):
        """当前档与**第 0 档（基准：工作日）**差几格；结构不同返回 None。"""
        gs = self._groups or []
        if len(gs) < 2:
            return None
        base = self._times(gs[0])
        cur = self._times(gs[max(0, min(self._cur, len(gs) - 1))])
        if len(base) != len(cur):
            return None                      # 行数都不一样 ⇒ 不比，避免误导
        # ★ 按**时间值**逐个比（首班、末班各算一个），不是按"行"比：
        #   一行里只有首班变了、末班没变，按行算会把这一行算成"变了"，
        #   用户数格子时对不上。
        return sum((a[0] != b[0]) + (a[1] != b[1])
                   for a, b in zip(base, cur))

    def _sync_diff_label(self) -> None:
        lab = getattr(self, "_diff_label", None)
        if lab is None:
            return
        gs = self._groups or []
        if len(gs) < 2 or self._cur <= 0:
            lab.hide()                       # 只有一档 / 正看着基准档 ⇒ 不需要提示
            return
        n = self._diff_vs_base()
        base = gs[0].date
        if n is None:
            lab.hide()
        elif n == 0:
            # ★ 文字要**短**：右侧面板可用宽只有 356px，实测
            #   "…（官方三档时刻一致，不是没切换）" 那版文字宽 **390px** 会撑爆。
            lab.setText("与「%s」完全相同" % base)
            lab.show()
        else:
            lab.setText("与「%s」相比：%d 个时刻不同" % (base, n))
            lab.show()

    def _norm_idx(self, v) -> int:
        """把信号实参统一成下标（int / str 都收得下）。"""
        if isinstance(v, str):
            names = [g.date for g in (self._groups or [])]
            return names.index(v) if v in names else 0
        try:
            return int(v)
        except Exception:
            return 0

    def _on_date_changed(self, *args) -> None:
        """切换日期类型：只切可见性，**不重建**（重建会让旧引用悬垂，见 __init__ 注释）。

        ★ v2.6.10：`activated` 与 `currentIndexChanged` 都连到这儿，
          同一手势可能触发两次 —— 槽是**幂等**的（设置 `_cur` + 切可见性），
          重复执行没有任何副作用。
        """
        idx = self._norm_idx(args[0] if args else
                             (self.date_combo.currentIndex()
                              if self.date_combo is not None else 0))
        self._cur = idx
        for i, box in enumerate(self._group_boxes):
            box.setVisible(i == idx)
        self._apply_combo_style()
        self._sync_diff_label()
        self.changed.emit()

    def _build_ui(self) -> None:
        """**只按现有模型重建控件，不重新解析**（空的新行才不会被丢掉）。"""
        self._clear_ui()
        self.date_combo = self._new_combo()     # ★ 每次新建（原因见 __init__ 注释）
        # ★ 槽位必须在**算列宽之前**定好：v2.6.15 起下拉并进了网格第 0 列，
        #   第 0 列的宽度 = max(线路名宽, 下拉宽) ⇒ 顺序反了列宽就是错的
        #   （会拿上一轮的槽位算，切站/切档后整表错位）。
        self._slot = self._combo_slot()
        self._compute_cols()          # ★ 列宽随内容变，每次重建都要重算
        # ★ v2.7.11：先把「＋ 添加一行」建出来，交给表头挂在「末班」右边
        #   （用户原话「首末班车的『+添加一行』的按钮挪动到文字『末班』的右侧」）。
        self._btn_add = self._make_add_row_btn()
        self._v.addWidget(self._make_header())
        # ★ 三种日期类型的全部控件都建出来，只是把不显示的那组藏起来。
        #   列宽是按**所有组**实测的 ⇒ 切换类型时列宽不会跳。
        self._group_boxes = []
        for g in self._groups:
            box = self._make_group(g)
            self._group_boxes.append(box)
            self._v.addWidget(box)
        self._sync_combo()
        for i, box in enumerate(self._group_boxes):
            box.setVisible(i == max(0, self._cur))
        for s in self._leftovers:
            lab = QLabel(s)
            lab.setStyleSheet("color:#94a3b8;font-size:11px;")
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._v.addWidget(lab)

        # v2.6.10：与基准档（工作日）的差异提示 —— 见 `_sync_diff_label` 的说明。
        # ★ 字号用 QFont 设（样式表的 font-size 不反映到 font()，见 §4.13b）。
        self._diff_label = QLabel()
        f_d = QFont(FONT_FAMILY)
        f_d.setPointSizeF(11.0)
        self._diff_label.setFont(f_d)
        self._diff_label.setStyleSheet("color:#94a3b8;")
        # ★ 必须允许折行：右侧面板可用宽只有 356px，不折行的话这行会
        #   把 sizeHint 撑到 390px（实测），面板横向溢出。
        self._diff_label.setWordWrap(True)
        self._v.addWidget(self._diff_label)
        self._sync_diff_label()

        # ★ v2.7.11：按钮已改挂到表头「末班」右侧（见 `_make_header`），
        #   这里不再往竖直布局里加，**整体高度不变**（原来它单独占的一行没了，
        #   表头那一行也没变高 —— 按钮压到 24px，跟表头文字一样高）。
        self._btn_add = getattr(self, "_btn_add", None)

    def _make_add_row_btn(self) -> QPushButton:
        """「＋ 添加一行」按钮（v2.7.11：挂在表头「末班」右侧）。"""
        add = QPushButton("＋ 添加一行")
        add.setCursor(Qt.PointingHandCursor)
        add.setMinimumHeight(24)
        add.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        add.setStyleSheet(
            "QPushButton{border:1px dashed #b9c0cb;border-radius:8px;"
            "background:transparent;color:#1976d2;padding:3px 10px;font-size:11px;}"
            "QPushButton:hover{background:#eff6ff;border-color:#1976d2;}")
        add.clicked.connect(self._add_row)
        return add

    # ---------------- 表头 ----------------
    def _prep_grid(self, g: QGridLayout) -> None:
        """把列宽钉死，并留一个**拉伸列**吸收多余宽度。

        ★★ 为什么必须多留一列 `len(COLS)` 设为 stretch=1：
          表格只占 ~430px，而表单可用宽 ~720px，多出来的 ~290px 得有地方去。
          不给拉伸列的话，QGridLayout 会把余量**摊给已有的列**，
          于是各列被撑宽 —— 表头（窄标签、几乎不撑）和分组网格
          （控件宽度不一、撑的幅度不同）**摊到的量不一样** ⇒ 两边彻底错位。
          留一个空拉伸列后，前 `len(COLS)` 列恒等于"最小值"，两边必然对齐。
        """
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(getattr(self, "_gap", GAP_COL))
        g.setVerticalSpacing(4)
        for i, w in enumerate(self.COLS):
            g.setColumnMinimumWidth(i, w)
            g.setColumnStretch(i, 0)
        g.setColumnMinimumWidth(len(self.COLS), 0)
        g.setColumnStretch(len(self.COLS), 1)        # ← 余量全丢给这一列

    def _apply_line_ring(self, ed: QLineEdit) -> None:
        """给线路名这一格套上**这条线路官方色**的外圈（v2.6.16）。

        用户原话：「下拉菜单『工作日』下方目前是显示各个线路对应的颜色块，
        改为在对应的线路文字套一个颜色外圈」
        ⇒ 颜色信息从"表头下面一条图例"改成"**画在字上**"：
          「1号线」外面那圈就是 1 号线的红，指认关系一眼到位，
          还省掉了色块条那一整行高度。

        ★ 外圈颜色**跟着当前输入的文字走**（`textChanged`）：
          用户把"1号线"改成"7号线"的瞬间外圈会跟着换色，
          不会出现"名字改了、颜色还对不上"的错位。
        ★ `lookup()` 查不到（新行还没填名字）时给中性灰 `#CBD5E1`，
          而不是报错或画个空的。
        ★ `hover` 时只改背景、**不动边框色**（否则鼠标一划过颜色就没了）；
          只有 `focus`（真正在编辑）才让位给蓝色，保留"正在编辑"的反馈。
        """

        def _paint() -> None:
            col = _LineDot.lookup(ed.text())
            ed.setStyleSheet(
                "QLineEdit#TTLine{border:1.5px solid %s;background:transparent;"
                "border-radius:7px;padding:2px 5px;}"
                "QLineEdit#TTLine:hover{background:#f5f7fa;}"
                "QLineEdit#TTLine:focus{border-color:#1976d2;background:#ffffff;}"
                % col)

        _paint()
        ed.textChanged.connect(lambda _t: _paint())

    def _make_header(self) -> QWidget:
        """表头一行：**[日期类型下拉] | 方向 | 首班 | → | 末班**

        布局（表头与内容行共用同一套 `self.COLS`，所以列严格对齐）：
        ```
                第0列          第1列   第2列  第3列  第4列
        表头:  [工作日▼]       方向    首班    →     末班
        内容:  [1号线]外圈红   往罗湖  06:02   →     23:47
        ```
        ★ v2.6.15（用户原话：「删除文字『线路』，但下方显示的内容如『一号线』
          放到表头如『工作日』正下方，其余表头等内容均往左挪动到合适位置」）
          ⇒ 两件事一起做：
          ① **删掉表头的「线路」文字**（这一列表头位置让给日期类型下拉）；
          ② 下拉从**网格外面**搬进**网格第 0 列**（正是线路名那一列）
             —— 于是"1号线"天然落在"工作日"的**正下方**；
             原来 `[槽位][间距]` 的 73px 缩进随之消失
             ⇒ 右侧「方向/首班/→/末班」四列整体**左移 66px**。
        ★ v2.6.8 当年为什么把下拉放到网格外面：怕它 71px 宽撑开第 0 列，
          而表头与内容行一旦用不同的列宽就整体错位。现在两边都用
          `self.COLS`，且第 0 列已经按 `max(线路宽, 下拉宽)` 钉死，
          这个顾虑不存在了（`_compute_cols`）。
        ★ v2.6.16：下拉下方那条**线路色块条已删掉** —— 用户要的是
          「在对应的线路文字**套一个颜色外圈**」（见 `_apply_line_ring`），
          色块条那种"图例"是多余的：外圈就画在"1号线"这几个字上，
          指认关系直接，还省了一整行高度。
        """
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 4)
        v.setSpacing(2)

        g = QGridLayout()
        self._prep_grid(g)

        # ---------------- 第 0 列：只有日期类型下拉 ----------------
        if self._slot and self.date_combo is not None:
            g.addWidget(self.date_combo, 0, 0, Qt.AlignCenter)
        else:
            # 只有一种日期类型 ⇒ 不显示下拉。但**这一列不能空着**：
            # `setColumnMinimumWidth()` 对"一个控件都没有的列"不可靠
            # （实测表头整行往左偏了 8px = 一个间距），塞个固定宽占位才撑得住。
            ph = QLabel("")
            ph.setFixedWidth(self._col_line)
            g.addWidget(ph, 0, 0)

        # ---------------- 第 3 列：箭头（同样要占位控件） ----------------
        ph = QLabel("→")
        ph.setFixedWidth(self._col_arrow)
        ph.setAlignment(Qt.AlignCenter)
        ph.setStyleSheet("color:#b6bcc7;font-size:11px;")
        g.addWidget(ph, 0, 3, Qt.AlignCenter)

        # ---------------- 第 1/2/4 列：文字表头（★ 没有「线路」了） ----------------
        # (列, 文字, 该列的宽度)  —— ★ 宽度就是下方内容的宽度，保证中心对齐
        for col, txt, cw in ((1, "方向", self._col_dir),
                             (2, "首班", self._col_time),
                             (4, "末班", self._col_time)):
            lab = QLabel(txt)
            f = QFont(FONT_FAMILY)
            f.setPointSizeF(TT_HEADER_PT)
            f.setBold(True)
            lab.setFont(f)
            lab.setStyleSheet(f"color:{TT_HEADER_COLOR};")
            lab.setFixedWidth(cw)           # ★ 与下方内容等宽
            lab.setAlignment(Qt.AlignCenter)  # ★ 文字居中 ⇒ 与下方中心重合
            g.addWidget(lab, 0, col, Qt.AlignCenter)

        # ★ v2.7.11：「＋ 添加一行」搬到**「末班」右边**（用户要求）。
        #   放在第 `len(COLS)` 列 —— 那是 `_prep_grid` 留下的**拉伸列**，
        #   位置正好紧贴「末班」右侧、且**不会改动 0~4 任何一列的宽度**
        #   （用户原话「务必不能破坏现有的空间占用情况」）。
        if getattr(self, "_btn_add", None) is not None:
            g.addWidget(self._btn_add, 0, len(self.COLS),
                        Qt.AlignLeft | Qt.AlignVCenter)
        v.addLayout(g)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#e3e8ef;")
        v.addWidget(sep)
        return box

    # ---------------- 一个日期类型分组 ----------------
    def _make_group(self, g: _Group) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        # v2.6.7：日期胶囊去掉了 —— 顶部那个下拉菜单已经在显示是哪种日期类型了，
        # 再挂一颗同名的胶囊纯属重复占位。（`g.date_ed` 不再创建，`text()`
        # 会退回用 `g.date`，拼接结果与原来完全一致。）
        g.date_ed = None

        grid = QGridLayout()
        self._prep_grid(grid)
        r = 0
        for row in g.rows:
            n = max(1, len(row.items))
            row.line_ed = _mk_line("TTLine", row.orig_line_name,
                                   pt=9.5, bold=True)
            row.line_ed.setPlaceholderText("线路")
            row.line_ed.setFixedWidth(self._col_line)
            row.line_ed.setAlignment(Qt.AlignCenter)        # ★ 居中
            # ★ v2.6.16：外圈 = 这条线路的官方色（替掉原来表头下方的色块条）
            self._apply_line_ring(row.line_ed)
            # ★ v2.6.15：第 0 列 = 「线路名」内容（表头位置是日期类型下拉）。
            #   用户要的就是"一号线"落在"工作日"**正下方**，所以两者必须同列。
            grid.addWidget(row.line_ed, r, 0, n, 1, Qt.AlignCenter)

            for k, it in enumerate(row.items):
                y = r + k
                de = _mk_line("TT", it.get("dir", ""))
                de.setPlaceholderText("往…")
                de.setFixedWidth(self._col_dir)
                de.setAlignment(Qt.AlignCenter)             # ★ 居中
                fe = _mk_line("TTFirst", it.get("first", ""), QSS_FIRST,
                              pt=TT_TIME_PT, bold=True)
                fe.setFixedWidth(self._col_time)
                fe.setAlignment(Qt.AlignCenter)
                fe.setPlaceholderText("首")
                le = _mk_line("TTLast", it.get("last", ""), QSS_LAST,
                              pt=TT_TIME_PT, bold=True)
                le.setFixedWidth(self._col_time)
                le.setAlignment(Qt.AlignCenter)
                le.setPlaceholderText("末")
                arrow = QLabel("→")
                arrow.setStyleSheet("color:#b6bcc7;font-size:11px;")
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setFixedWidth(self._col_arrow)   # ★ 与表头等宽

                grid.addWidget(de, y, 1, Qt.AlignCenter)
                grid.addWidget(fe, y, 2, Qt.AlignCenter)
                grid.addWidget(arrow, y, 3, Qt.AlignCenter)
                grid.addWidget(le, y, 4, Qt.AlignCenter)
                it["_dir_ed"], it["_first_ed"], it["_last_ed"] = de, fe, le
            r += n
        # ★★ v2.6.15：**不再需要"让出下拉槽位"的占位了**。
        #   v2.6.8 那会儿下拉在网格外面，所以内容行必须用 QHBoxLayout 补一个
        #   同宽占位，否则表头有下拉、内容行没有 ⇒ 整表错开一个槽位（实测 77px）；
        #   现在是**表头与内容行同一个网格的第 0 列**（上面是下拉、下面是线路名），
        #   占位这一层整个删掉，少一层嵌套也少一处会错位的地方。
        v.addLayout(grid)
        return box

    def current_date(self) -> str:
        """当前下拉里选中的日期类型（没有分组时返回空串）。"""
        gs = self._groups or []
        if not gs:
            return ""
        return gs[max(0, min(self._cur, len(gs) - 1))].date

    def _add_row(self) -> None:
        if not self._groups:
            self._groups.append(_Group("工作日"))
        row = _LineRow("", [], "")
        row.items = [{"dir": "", "first": "", "last": ""}]
        row.keep = True                     # ★ 空也不许丢
        # ★ v2.6.7：加到**当前正在看**的那一组（原来是写死加到最后一组）
        gs = self._groups
        gs[max(0, min(self._cur, len(gs) - 1))].rows.append(row)
        self._build_ui()
        self.changed.emit()

    # ================================================== 拼回存储格式
    def text(self) -> str:
        """拼回 `工作日 · 1号线：往罗湖 首06:02 末23:47；往机场东 首06:41 末23:21`。

        ★ 没动过的行**原样吐回**（见文件头说明）。
        """
        out: List[str] = []
        for g in self._groups:
            date = (g.date_ed.text().strip() if g.date_ed is not None
                    else g.date)
            for row in g.rows:
                ln = (row.line_ed.text().strip() if row.line_ed is not None
                      else row.orig_line_name)
                cur = []
                for it in row.items:
                    de = it.get("_dir_ed")
                    fe = it.get("_first_ed")
                    le = it.get("_last_ed")
                    d = de.text().strip() if de is not None else it.get("dir", "")
                    f = fe.text().strip() if fe is not None else it.get("first", "")
                    l = le.text().strip() if le is not None else it.get("last", "")
                    if d or f or l:
                        cur.append((d, f, l))
                if (row.orig_line and row.orig_items
                        and row.orig_line_name == ln
                        and row.orig_items == cur
                        and g.date == date):
                    out.append(row.orig_line)          # ← 一字未动，原样保留
                    continue
                if not ln and not cur:
                    if row.keep:
                        continue                        # 用户新加的空行：下次重建仍在
                    continue
                body = "；".join("%s 首%s 末%s" % t for t in cur)
                out.append("%s · %s：%s" % (date, ln, body) if ln else body)
        out.extend(getattr(self, "_leftovers", []))
        return "\n".join(out)


class _LineDot(QWidget):
    """线路官方颜色的小圆点（让每条线一眼可辨）。

    ★ 历史上它占过表格第 0 列（v2.6.10 及更早）、也做过表头下方的色块条
      （v2.6.11~v2.6.15）。v2.6.16 起这两处都不要了 —— 颜色直接画成
      **线路名文字的外圈**（`_apply_line_ring`）。
    ★★ 但 `lookup()` 仍然是"**线路名 → 官方色**"的**唯一入口**
      （外圈、色块条都走它），别在别处另写一份取色逻辑。
    """

    _COLOR_CACHE: Dict[str, str] = {}

    def __init__(self, line_name: str, parent=None, size: int = None):
        super().__init__(parent)
        self._color = self.lookup(line_name)
        sz = max(10, (16 if size is None else size) - 2)
        self.setFixedSize(sz, sz)

    @classmethod
    def lookup(cls, line_name: str) -> str:
        """按线路**名字**反查线路 id 再取官方颜色；查不到给灰点。

        ★ 结果按名字缓存：每个方向都查一次的话，一个站十几行 => 每 reparse 一次
          就要把 20 条线路遍历十几遍。
        """
        key = (line_name or "").strip()
        if not key:
            return "#CBD5E1"
        hit = cls._COLOR_CACHE.get(key)
        if hit is not None:
            return hit
        color = "#CBD5E1"
        try:
            dm = get_data_manager()
            for ln in dm.all_lines():
                if (ln.get("name") or "").strip() == key:
                    color = dm.line_color(ln.get("id"), "#CBD5E1")
                    break
        except Exception:
            pass
        cls._COLOR_CACHE[key] = color
        return color

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor
        from PySide6.QtCore import QRectF
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._color))
        p.drawEllipse(QRectF(self.rect()).adjusted(1.5, 4.0, -1.5, -4.0))
        p.end()
