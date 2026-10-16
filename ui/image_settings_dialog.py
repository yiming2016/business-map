# -*- coding: utf-8 -*-
"""v2.7.14「看图模式」的 ⚙️ 设置弹窗。

用户原话：「编辑相关的按钮，增添⚙️，内部可以设置
  ① 是否编辑完成后立即保存为图片
  ② 多少分钟保存一次
  ③ 退出前询问保存」。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from ui.image_mode import default_png_path

# ★ v2.7.18：与 main_window 里的浮层限幅常量保持一致（360 / 780）
INFO_PANEL_MIN_W = 360
INFO_PANEL_MAX_W = 780

# ★ v2.7.24：数字字段宽度 132 → 104（「右侧面板宽度」和「拖动留白」并到一行后，
#   两个字段 + 两个标签必须塞进 438px 内的可用宽度）
# ★ v2.7.26：用户「把单位 px 独立出去，不要显示在输入框」（截图里框内 "500 p)" 被
#   箭头挤掉半个 x）⇒ 后缀从 QSpinBox 里拿掉、改成框**右侧一个独立小标签**，
#   字段因此可以收短（104 → 72）。
# ★★ v2.7.27：用户「两个输入框只能显示一位数字，增加输入框长度，至少可以显示 4 位数字」
#   ⇒ 不再硬编码宽度，按**当前字体**算出"放得下 4 个 0 + 上下箭头 + 边框"的宽度：
#       arrows ≈ 控件高度（Qt 的上下箭头是正方形）、边框 + 内部留白给 12px 余量、
#       文字用 fontMetrics 实测（全局字体是 10pt 加粗，别按"普通号"拍脑袋）。
FIELD_MIN_DIGITS = 5      # ★ 用户要"至少 4 位"，多留一位当余量（真机字形更宽）
FIELD_W_MIN = 104         # 下保底：字号再小也不窄于这个数

# ★★ v2.7.30：拖动余量的可填范围。
#   之前写死 0~400 —— QSpinBox 是**逐字符**校验的：键入 500 时中间态 500 > 400
#   ⇒ 最后一个字符被直接吞掉、退回 50。用户看到的就是「无法输入三位数」。
#   现在抬到 9999（四位数都能敲进去，彻底不会再被吞字符）。这个值越大只是
#   "允许拖得越远"，没有副作用 —— 日常 0~200 就够，见 tooltip 的建议。
#   ★ main_window._saved_pan_pad() 必须引用同一个常量 —— 那边还有一个 min(400, v)
#     的兜底夹取，漏改的话重启后新值还是会被夹回去。
PAN_PAD_MIN = 0
PAN_PAD_MAX = 9999

# ★ v2.7.30：自动出图间隔（分钟）。同样为了不被吞字符，上限放宽到一天。
INTERVAL_MIN_MIN = 1
INTERVAL_MIN_MAX = 1440


def spin_field_width(spin, digits: int = FIELD_MIN_DIGITS) -> int:
    """给数字框算一个"至少能完整显示 digits 位数字"的宽度。"""
    fm = spin.fontMetrics()
    text = fm.horizontalAdvance("0" * digits)          # 数字的实宽
    arrows = max(18, spin.sizeHint().height())         # 上下箭头 ≈ 正方形
    return max(FIELD_W_MIN, text + arrows + 12)


def make_int_spin(spin, lo: int, hi: int, val: int, step: int = 1,
                  fixed: bool = True) -> None:
    """★ v2.7.30：给本弹窗所有数字框套同一套口径，避免逐个漏改。

    背景（用户原话「每次我都无法输入三位数」）：QSpinBox 是**逐字符**校验的，
    range 上限写死 400 时，键入 500 的最后一刻 500 > 400 ⇒ 那个字符被吞掉，
    框里停在 50 ⇒ 看上去就像"三位数输不进去"。放宽 range 才是根治手段。
    """

    spin.setRange(int(lo), int(hi))
    spin.setSingleStep(int(step))
    spin.setKeyboardTracking(False)      # v2.7.28：打字中间态不再实时应用
    # ★ 刻意**不**用 CorrectToNearestValue。实测两条结论（tools/_dbg_spin3 类2）：
    #   ① 它只在 editingFinished 时纠错，**治不了键入过程中的吞字符**（输 9999
    #      仍然停在 999，最后一个字符照样被吃掉）—— 吞字符只能靠放宽 range 根除；
    #   ② minimum > 0 的框用它反而更坑：面板宽度 range 360~780 时键入 999，
    #      默认模式会保留原值 520（用户看得懂），Nearest 却把它拉到**下界 360**。
    spin.setCorrectionMode(QAbstractSpinBox.CorrectToPreviousValue)
    spin.setValue(int(val))
    if fixed:                                    # 带框内后缀的框不能按位数定宽
        spin.setFixedWidth(spin_field_width(spin))


class ImageSettingsDialog(QDialog):
    # ★ v2.7.19：面板宽度**实时生效** —— 数字一变就发信号，外面立刻改面板 +
    #   写进设置（用户原话「右侧面板宽度的数值设置为实时改动」，不必点确定）
    info_w_changed = Signal(int)
    # ★ v2.7.20：拖动留白（场景单位）实时生效
    pan_pad_changed = Signal(int)

    def __init__(self, parent, sec: dict, data_dir, info_w_max=None):
        super().__init__(parent)
        self.setWindowTitle("看图模式 / 界面设置")
        self.data_dir = data_dir
        self.sec = dict(sec)
        # ★ v2.7.28：本机真正能到的面板宽度上限（= min(780, 屏宽×55%)，由外面传入）。
        #   数字框的上限就按它收紧 —— 否则输入 780 会被 _overlay_width_cap() 静默
        #   夹到 751，用户看到的就是"输入了数字但没反应"。
        self._info_w_max = int(info_w_max or INFO_PANEL_MAX_W)
        self._info_w_max = max(INFO_PANEL_MIN_W,
                               min(INFO_PANEL_MAX_W, self._info_w_max))

        root = QVBoxLayout(self)
        # ★★ v2.7.20：**分区块**重排（用户：「弹窗有些乱，重新规划一下空间」）。
        #   原来 4 个勾选项被表单 label 列挤到很深（左侧一大片空白），数字框又被
        #   拉到超长。现在拆成两块，各带小标题：
        #     「看图模式」——4 个勾选项 + 定时行（一律**顶格**，不再缩进）
        #     「界面 / 地图」——面板宽度 / 图片保存位置 / 拖动留白（label + 短字段）
        #   两条区块之间一条细分隔线，视觉上一眼分清"哪个设置管什么"。
        def _section(title):
            lb = QLabel(title)
            f = lb.font()
            f.setBold(True)
            lb.setFont(f)
            lb.setStyleSheet("color:#5A6673; margin-top:6px;")
            return lb

        def _hline():
            from PySide6.QtWidgets import QFrame
            ln = QFrame()
            ln.setFrameShape(QFrame.HLine)
            ln.setFrameShadow(QFrame.Sunken)
            ln.setStyleSheet("color:#D7DCE2;")
            return ln

        def _lab(text):
            # ★ v2.7.23：用户「全部都要左对齐」⇒ 标签一律**顶格左对齐**
            #   （原来 AlignRight 会让"右侧面板宽度："缩进到中间，跟"图片存到："
            #   顶格的样子打架）。字段列仍统一到同一条竖线。
            lb = QLabel(text)
            lb.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            return lb

        def _unit(text="px"):
            # ★ v2.7.26：单位独立成框外的灰色小标签（框内只留数字）
            lb = QLabel(text)
            lb.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lb.setStyleSheet("color:#5A6673;")
            lb.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            return lb

        # ---------------- 区块 1：看图模式 ----------------
        # ★ v2.7.21：区块 1 改 **QVBoxLayout**（原来 QGridLayout 三列 —— 但这里
        #   每一行都是"跨满整行"的，列宽分配反而让右端留出 30px 空隙，
        #   按钮贴不到最右）。竖排后每行都吃满宽度，「立即生成」自然顶到行尾。
        grid = QVBoxLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)
        self._grid = grid

        # ★ v2.7.25：两条勾选项并排一行（用户：「把『启动软件后自动生成一次、
        #   直接进看图模式』放到『切到看图模式时自动生成图片』右侧」）。
        #   两条原话加起来真机约 600px，塞不进 438px 可用宽度 ⇒ 用户点选
        #   "缩短两条文字"，原话保留在悬停提示里。
        self.cb_auto = QCheckBox("看图模式自动出图")
        self.cb_auto.setChecked(bool(self.sec.get("auto_on_enter", True)))
        self.cb_auto.setToolTip(
            "「切到看图模式时自动生成图片」\n"
            "勾上 = 一点「看图模式」就立刻把整张图烘成位图并保存；\n"
            "不勾 = 只在齿轮里点「立即生成」时才出图。")

        self.cb_start = QCheckBox("启动时自动生成并进看图")
        self.cb_start.setChecked(bool(self.sec.get("auto_on_start", True)))
        self.cb_start.setToolTip(
            "「启动软件后自动生成一次、直接进看图模式」\n"
            "关掉的话，开软件先进编辑模式（出图要几秒，看你要不要省这几秒）。")

        row_top = QHBoxLayout()
        row_top.setContentsMargins(0, 0, 0, 0)
        row_top.setSpacing(6)
        row_top.addWidget(self.cb_auto)
        row_top.addSpacing(20)          # 两条之间压缩后的间距
        row_top.addWidget(self.cb_start)
        row_top.addStretch(1)
        self._row_top = row_top
        grid.addWidget(self._wrap(row_top))

        # ★ v2.7.21：「🔄 立即生成」挪到本行**最右**（v2.7.19 时放在最左）
        row_int = QHBoxLayout()
        row_int.setContentsMargins(0, 0, 0, 0)
        self.cb_timer = QCheckBox("每隔")
        self.cb_timer.setChecked(int(self.sec.get("interval_min", 0) or 0) > 0)
        self.sp_min = QSpinBox()
        # ★ v2.7.30：同样走统一口径（fixed=False —— 它有框内后缀「 分钟」，
        #   宽度得让 Qt 自己按内容算，不能套"按位数定宽"）。
        #   上限 240 → 1440（= 一天）：同样是为了不让多位数字被吞字符。
        make_int_spin(self.sp_min, INTERVAL_MIN_MIN, INTERVAL_MIN_MAX,
                      int(self.sec.get("interval_min", 0) or 5), fixed=False)
        self.sp_min.setSuffix(" 分钟")
        self.sp_min.setEnabled(self.cb_timer.isChecked())
        self.cb_timer.toggled.connect(self.sp_min.setEnabled)
        row_int.addWidget(self.cb_timer)
        row_int.addWidget(self.sp_min)
        lb_int = QLabel("自动出图")
        lb_int.setToolTip("每隔上面这个分钟数，自动把整张图重新生成并保存一次")
        row_int.addWidget(lb_int)
        row_int.addStretch(1)          # ★ 弹性空白把按钮顶到本行最右
        btn_now = QPushButton("🔄 立即生成")
        btn_now.setToolTip("不等定时器，现在就把整张图重新烘一遍并存成 png")
        btn_now.clicked.connect(self._rebuild_now)
        btn_now.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)   # 不再铺满整行
        row_int.addWidget(btn_now)
        grid.addWidget(self._wrap(row_int))

        self.cb_exit = QCheckBox("退出程序前询问是否保存为图片")
        self.cb_exit.setChecked(bool(self.sec.get("ask_on_exit", True)))
        grid.addWidget(self.cb_exit)

        root.addWidget(_section("看图模式"))
        root.addLayout(grid)
        root.addWidget(_hline())

        # ---------------- 区块 2：界面 / 地图 ----------------
        root.addWidget(_section("界面 / 地图"))
        # ★ v2.7.24：用户把「拖动留白」挪到「右侧面板宽度」**同一行右侧**，并要求
        #   压缩间距 ⇒ 这一块不再用网格（网格的标签列会把两行硬拆开、字段列也会
        #   把右边的项推到很远处），改**竖排 + 每行内部横排**，和区块 1 一个写法：
        #     row0: 右侧面板宽度：[..]   拖动留白：[..]     ← 两组之间 24px
        #     row1: 图片存到：
        #     row2: [====== 路径框 ======] [浏览…]
        grid2 = QVBoxLayout()
        grid2.setSpacing(8)
        grid2.setContentsMargins(0, 0, 0, 0)
        self._grid2 = grid2

        # ★ v2.7.18：右侧面板默认宽度（拖边缘改宽会自动记进这里）
        self.sp_info_w = QSpinBox()
        # ★ v2.7.30：统一口径（range / 回车才生效 / **越界夹到边界** / 宽度按字体算）
        #   —— 逐个 setXXX 容易漏，漏一个就会出现"某些数字输不进去"。
        make_int_spin(self.sp_info_w, INFO_PANEL_MIN_W, self._info_w_max,
                      int(self.sec.get("info_panel_w", 520) or 520), step=10)
        self.sp_info_w.setToolTip(
            "右侧「站点详情」面板的宽度。\n"
            f"可调范围 {INFO_PANEL_MIN_W} – {self._info_w_max}（上限 = 780 与"
            "屏幕可用宽度×55% 取小，这台机器上就是 "
            f"{self._info_w_max}）。\n"
            "在软件里直接拖面板左边缘改宽，也会自动记到这里（下次启动沿用）。\n"
            "★ 左侧线路面板同时开着时，两侧合计要给地图至少留 320px，\n"
            "  这时本框会自动显示**真正落地**的那个宽度。")
        # ★ v2.7.19：实时生效（数字一变就通知外面改面板 + 写设置）
        self.sp_info_w.valueChanged.connect(
            lambda v: self.info_w_changed.emit(int(v)))

        self.ed_path = QLineEdit(self.sec.get("png_path") or default_png_path(data_dir))
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse)
        # ★★ v2.7.23：用户「我之所以让你把路径另起一行，就是为了能看全文件路径，
        #   你现在却把'浏览'按键加长了」⇒ 按钮**只按自身尺寸**，绝不参与拉伸，
        #   多余宽度全部留给路径框。
        btn_browse.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        btn_browse.setFixedWidth(max(64, btn_browse.sizeHint().width() + 8))
        self._btn_browse = btn_browse

        # ★ v2.7.29：语义从"拖动留白"改成"**面板外额外余量**"。
        #   左右两侧现已各自**自动跟随**那侧浮层面板盖住的宽度（盖多少就腾多少，
        #   站点再也不会被拖到「站点详情」/ 线路面板底下），这里只调"再多放开多少"。
        self.sp_pan_pad = QSpinBox()
        # ★★ v2.7.30：上限 400 → 2000，且走统一口径（越界夹边界、不再吞字符）
        make_int_spin(self.sp_pan_pad, PAN_PAD_MIN, PAN_PAD_MAX,
                      int(self.sec.get("pan_pad_scene", 24) or 0), step=10)
        self.sp_pan_pad.setToolTip(
            "拖动地图时，**元素离画面边缘最少保留多远**（左右两侧还会各自\n"
            "自动加上那侧浮层面板的宽度，站点不会被拖到「站点详情」底下）。\n"
            "0 = 元素最多能贴到面板边缘；**调大 = 元素离边缘更远、更安全**。\n"
            "它是 1.0 倍时的像素数，放大后屏幕上会按比例变大。\n"
            f"可填范围：{PAN_PAD_MIN} ~ {PAN_PAD_MAX}，日常 **0 ~ 200** 就够。\n"
            "★ 注：**整张图本来就装得下**（整图适配那一档）时画面本来就居中，\n"
            "  这时改这个数是看不出差别的 —— 要先放大到能拖动为止。")
        self.sp_pan_pad.valueChanged.connect(
            lambda v: self.pan_pad_changed.emit(int(v)))

        # ★ v2.7.24：row0 —— 「右侧面板宽度」与「拖动留白」**同一行**（用户要求），
        #   两组之间只留 20px（"适当压缩间距"）。
        # ★ v2.7.26：两个数字框的单位「px」不再画在框内，而是各自跟在框**右侧**
        #   一个灰色小标签（框内只留数字 ⇒ 三位数不会被箭头挤掉）。
        row_a = QHBoxLayout()
        row_a.setContentsMargins(0, 0, 0, 0)
        row_a.setSpacing(4)           # 框与它的单位贴紧一点
        row_a.addWidget(_lab("右侧面板宽度："))
        row_a.addWidget(self.sp_info_w)
        self._lb_px_info = _unit("px")     # 探针用
        row_a.addWidget(self._lb_px_info)
        row_a.addSpacing(18)          # ★ 两组之间（"适当压缩间距"）
        row_a.addWidget(_lab("拖动余量："))
        row_a.addWidget(self.sp_pan_pad)
        self._lb_px_pad = _unit("px")      # 探针用
        row_a.addWidget(self._lb_px_pad)
        row_a.addStretch(1)
        grid2.addWidget(self._wrap(row_a))

        # ★ v2.7.21：用户要"图片保存到的路径另起一行" ⇒ 标签独占一小行，
        #   输入框 + 浏览…落到下一行（输入框因此长了很多）。
        # ★★ 标签顶格左对齐，与「看图模式」区块的勾选项顶同一条竖线
        #   （一开始放在字段列 ⇒ 缩进到 105px，用户：「图片保存相关的你要左对齐啊」）。
        lb_path = QLabel("图片存到：")
        lb_path.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._lb_path = lb_path          # 探针用
        grid2.addWidget(lb_path)

        row_p = QHBoxLayout()
        row_p.setContentsMargins(0, 0, 0, 0)
        row_p.setSpacing(6)
        row_p.addWidget(self.ed_path, 1)   # 输入框吃掉全部剩余宽度
        row_p.addWidget(btn_browse)        # 按钮固定尺寸，不吃宽度
        self._row_path = row_p
        grid2.addWidget(self._wrap(row_p))

        root.addLayout(grid2)
        root.addStretch(1)

        # ★ v2.7.19：只剩「确定」（用户：删除 Cancel）。手写按钮以免出现英文 OK
        row_ok = QHBoxLayout()
        row_ok.addStretch(1)
        btn_ok = QPushButton("确定")
        btn_ok.setDefault(True)
        btn_ok.setMinimumWidth(84)
        btn_ok.clicked.connect(self.accept)
        row_ok.addWidget(btn_ok)
        root.addLayout(row_ok)

        self._rebuild = False
        self._btn_now = btn_now
        self.setMinimumWidth(460)
        self.adjustSize()

    def show_applied_w(self, w: int) -> None:
        """★ v2.7.28：外面把**真正落地**的宽度回写显示（不许框里留假数字）。

        输入 700 但左侧线路面板占着地盘时，实际只能给 640 ⇒ 框里显示 640，
        用户立刻明白为什么"没到 700"。★ 必须先掐断信号，否则 setValue 又触发
        valueChanged ⇒ 外面再改一次 ⇒ 死循环。
        """
        try:
            self.sp_info_w.blockSignals(True)
            self.sp_info_w.setValue(int(w))
        finally:
            self.sp_info_w.blockSignals(False)

    @staticmethod
    def _wrap(layout):
        from PySide6.QtWidgets import QWidget
        w = QWidget()
        w.setContentsMargins(0, 0, 0, 0)     # ★ v2.7.21：去掉内边距 ⇒ 行内按钮贴到最右
        w.setLayout(layout)
        return w

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "图片存到…", self.ed_path.text() or default_png_path(self.data_dir),
            "PNG 图片 (*.png)")
        if path:
            if not path.lower().endswith(".png"):
                path += ".png"
            self.ed_path.setText(path)

    def _rebuild_now(self):
        self._rebuild = True
        self.accept()

    def want_rebuild(self) -> bool:
        return bool(self._rebuild)

    def result_settings(self) -> dict:
        out = dict(self.sec)
        out["auto_on_enter"] = self.cb_auto.isChecked()
        out["interval_min"] = int(self.sp_min.value()) if self.cb_timer.isChecked() else 0
        out["ask_on_exit"] = self.cb_exit.isChecked()
        out["auto_on_start"] = self.cb_start.isChecked()
        out["png_path"] = self.ed_path.text().strip()
        out["info_panel_w"] = int(self.sp_info_w.value())
        out["pan_pad_scene"] = int(self.sp_pan_pad.value())
        return out
