"""
ui/info_panel.py
========================
右侧信息面板：

  - 顶部：站点名称（大字）
  - 中部：可编辑字段（按 EDITABLE_FIELDS 顺序排列）
        单行字段 → QLineEdit
        多行字段 → QPlainTextEdit
        bool    → QCheckBox
        lines   → 下拉多选（LinesSelect，收起时显示已选线路）
  - 底部按钮：[取消] [保存] [在弹窗中编辑]

  信号：
    save_requested(station_id, dict)  -> 用户按了保存
    edit_in_dialog_requested(station_id) -> 用户想用弹窗
    delete_requested(station_id) -> 用户想删除
    auto_saved(station_id)  -> 「改了没点保存」被自动兜住时发（给状态栏提示）

  ★ v2.6.57：改了字不点保存就切站 / 关窗口，之前是**静默丢弃**
    （用户原话「文字修改为之后可能不被保存」）。现在切走前先提交，见
    `_is_dirty()` / `flush_pending()`。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from PySide6.QtCore import Qt, Signal, QTimer, QSize, QEvent
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QPlainTextEdit, QCheckBox,
    QPushButton, QScrollArea, QFrame, QSizePolicy, QLayout,
    QComboBox, QToolButton, QMenu, QFileDialog,
)

from core.schema import (EDITABLE_FIELDS, derive_is_transfer,
                         HIDDEN_UI_FIELDS, READONLY_UI_FIELDS)
from core.data_manager import get_data_manager
from ui.widgets import LinesSelect, make_nursing_icon
# ★ v2.6.5：出入口 / 首末班车用**和编辑弹窗同一个控件**，
#   不再各写一份（同一字段两份代码 = 同一个 bug 修两遍，skill §1b 末）。
from ui.exits_editor import ExitsEditor
from ui.timetable_editor import TimetableEditor
# v2.6.8：表单行形态 + 高度自适应 —— 与编辑弹窗共用同一份实现
from ui.form_rows import make_stacked, make_inline_row, inject_head
from ui.autofit import AutoFitGroup


# ==== 并排行（v2.4.17：文字与输入框挤在**同一行**）====
# 面板比弹窗窄（约 380px），所以间隔和输入框宽度都比弹窗那套小一点
PANEL_PAIR_GAP = 18
# v2.4.18：150 → **170px**（跟着弹窗一起"变长一些"）。
#   实测面板可用宽 338px，并排行原占 318px、**只剩 20px 余量**，
#   所以这里最多只能给到 170px（318 + 20 = 338，正好用满不溢出）。
PANEL_LINE_EDIT_WIDTH = 170

# 面板里的字段 key（别硬编码"第几个字段"，跟着 schema 走）
EXITS_KEY = "exits"
TIMETABLE_KEY = "timetable"
# 「标签 + 单行输入框同排」里标签的固定宽度（与弹窗的 INLINE_LABEL_W 同概念）
PANEL_INLINE_LABEL_W = 56
# v2.6.8：多行输入框自动拉伸的**下限**（面板窄，比弹窗再小一点）
PANEL_AUTOFIT_MIN_H = 40


def _norm(v):
    """把"数据里的值"和"控件里的值"拉到同一个口径再比。

    ★ 必须做空值等价：数据里**没有**这个字段（None）和控件里的空串要算一样。
      否则"从没设过的字段"每次都被判成改动 ⇒ 每次切站都自动保存一次，
      撤销栈被灌满、还平白写盘（实测一上来就 diff，370 个站全"脏"）。
    ★ 数字也要归一：`5000`（数据）和 `"5000.0"`（控件）必须算同一个值。
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return v
    if isinstance(v, (list, tuple)):
        return tuple(sorted(str(x) for x in v))
    s = str(v).strip()
    if s == "":
        return ""
    try:
        return ("num", round(float(s), 4))
    except (TypeError, ValueError):
        return ("str", s)


# ★ v2.6.57：设 1 就退回"改了字不点保存 = 静默丢弃"的旧行为，
#   回归 `_chk_text_save.py` 用它做**变异自检**（判据必须跟着失败）。
AUTO_SAVE_PENDING = os.environ.get("METROEDITOR_NO_AUTOSAVE", "0") != "1"


class InfoPanel(QWidget):
    save_requested = Signal(str, dict)
    edit_in_dialog_requested = Signal(str)
    delete_requested = Signal(str)
    auto_saved = Signal(str)          # v2.6.57
    locate_requested = Signal(str)    # ★ v2.6.91：点 🎯 跳转到该站（同搜索定位）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_station_id: str = ""
        self._widgets: Dict[str, QWidget] = {}
        self._flushing = False        # v2.6.57：防 `_flush_pending` 重入
        # v2.6.8：多行输入框的"高度自动拉伸"（与编辑弹窗同一份实现）
        self._autofit = AutoFitGroup(min_h=PANEL_AUTOFIT_MIN_H)

        # ★ v2.6.77：面板整体加宽 1.5×（用户：「出入口信息的输入框改为
        #   现在长度的150%」—— 出入口内容框宽度随面板走，加宽面板即加长输入框）
        self.setMinimumWidth(480)
        self.setMaximumWidth(690)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ============================================================
        # ★ v2.6.79：**最上方**一排站点图片（可添加多张）—— 在站名输入框之上。
        #   横向缩略图条：左键看大图、右键移除、末尾 ＋ 多选添加。
        # ============================================================
        self._images: list = []          # covers/ 里的文件名（按顺序）
        self.img_scroll = QScrollArea()
        self.img_scroll.setWidgetResizable(True)
        self.img_scroll.setFrameShape(QFrame.NoFrame)
        self.img_scroll.setFixedHeight(104)
        self.img_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.img_scroll.setStyleSheet("""
            QScrollArea { background: #f7f8fa; border: 1px solid #e0e3e8; border-radius: 8px; }
        """)
        self.img_host = QWidget()
        self.img_host.setStyleSheet("background: transparent;")
        self.img_row = QHBoxLayout(self.img_host)
        self.img_row.setContentsMargins(6, 6, 6, 6)
        self.img_row.setSpacing(6)
        self.img_row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.img_scroll.setWidget(self.img_host)
        root.addWidget(self.img_scroll)

        # ★ v2.6.77：最上方就是**站点名称输入框**（原来是"📍 站名"只读大字 +
        #   表单里再放一个「站点名称 [输入框]」行，两处重复，全删）。
        #   ★ v2.6.79：顺序 = 图片排 → 站名 → 所属线路下拉 → 所属区下拉。
        #   ★ v2.6.80：站名/线路/区三者放**同一行**（用户截图纠偏）：
        #   [站名输入框(拉伸)] [线路下拉(固定宽)] [区下拉(固定宽)]。
        self.title = QLineEdit()
        self.title.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        self.title.setPlaceholderText("未选中站点")
        self.title.setMinimumHeight(32)   # ★ v2.6.80：与右侧两个下拉等高对齐
        # ★ v2.7.11：站名**默认居中显示**（用户原话「站点名称尽量居中显示，
        #   点击修改后再从左往右显示」）⇒ 平时 AlignCenter，一进焦点（点进来
        #   编辑）就切 AlignLeft，光标从左往右；失焦再切回居中。
        #   用事件过滤器而不是子类：title 在 show_station 里被反复 setText，
        #   换类型会牵动一堆引用（铁律：同一处只留一份）。
        self.title.setAlignment(Qt.AlignCenter)
        self.title.installEventFilter(self)
        # ★ v2.6.91：宽度锁到"现在长度的 40%"——在第一次 show_station 拿到
        #   实际布局宽度后定宽（构造时还没布局，量不到）。
        self._title_w_locked = False

        # ★ v2.6.91：站名输入框右侧的 🎯 小按钮 —— 点它跳转到该站
        #   （效果 = 搜索定位：选中 + 放大 2.5 倍 + 闪烁）。
        self.btn_locate = QToolButton()
        self.btn_locate.setText("🎯")
        self.btn_locate.setToolTip("跳转到此站点（放大 2.5 倍定位）")
        self.btn_locate.setCursor(Qt.PointingHandCursor)
        # ★ v2.7.11：32 → 28：给"线路下拉要显示完整"腾宽度（同一行，用户要求
        #   压缩别的控件、别动线路下拉的内容）。图标本身没变，只是外框小一圈。
        self.btn_locate.setFixedSize(28, 28)
        self.btn_locate.clicked.connect(self._emit_locate)

        # 「所属线路」「所属区」标签文字全删，控件自明。两个下拉是**常驻控件**
        # （建一次），show_station 时只刷值 —— _build_form 里只做登记
        # （进 _widgets 才能被 _collect 取到）。
        all_lines = get_data_manager().all_lines()
        self.top_lines_select = LinesSelect(all_lines, [])
        self.top_lines_select.setMinimumHeight(32)
        # ★★ v2.7.11：原来**死宽 150px**，而"2号线 10号线 11号线 14号线"
        #   （岗厦北）实测要 ~250px ⇒ 右边的线路被截成省略号
        #   （用户原话「让左侧包含线路的下拉菜单内容显示完整」）。
        #   ⇒ 改成"能长就长、封顶 260"，腾出来的宽度从「所属区」那边挤。
        self.top_lines_select.auto_fit_width = True   # ★ 宽度跟着线路名自适应
        self.top_lines_select.setMinimumWidth(150)

        self.top_district = QComboBox()
        _dfld = next((f for f in EDITABLE_FIELDS if f["key"] == "district"), None)
        for _v, _l in (_dfld.get("options") or []):
            self.top_district.addItem(_l, _v)
        self.top_district.setMinimumHeight(32)
        # ★ v2.7.12：80 是拍脑袋的固定值 —— 实测连"福田区"的**第三个字**
        #   都被截掉（用户原话「区的下拉菜单『区』字没有完全显示出来」）。
        #   ⇒ 改成**按最长选项实量**：文字宽 + 下拉箭头/内边距（实测 34px），
        #     下限 96px。宽出来的一点点从「所属线路」那边出，但线路下拉有
        #     stretch=1 + 自己的自适应宽度，不会跟着被挤回省略号。
        _dfm = QFontMetrics(self.top_district.font())
        _dtxt = max((_dfm.horizontalAdvance(_l)
                     for _v, _l in (_dfld.get("options") or [])), default=60)
        self.top_district.setFixedWidth(max(96, _dtxt + 34))

        # ★★ v2.7.0：母婴室标记 —— 「所属区」下拉**右侧**的奶嘴小图标，
        #   仅当该站 facilities 里含「母婴室」时显示（用户要求）。
        self.lbl_nursing = QLabel()
        self.lbl_nursing.setPixmap(make_nursing_icon(20).pixmap(20, 20))
        self.lbl_nursing.setFixedSize(22, 22)
        self.lbl_nursing.setToolTip("本站设有母婴室")
        self.lbl_nursing.hide()

        self.top_row = QHBoxLayout()
        self.top_row.setContentsMargins(0, 0, 0, 0)
        # ★ v2.7.11：6 → 4（同一行的控件多，间隙省下来的宽度正好给线路下拉）
        self.top_row.setSpacing(4)
        self.top_row.addWidget(self.title, 0)
        self.top_row.addWidget(self.btn_locate, 0)
        # ★ v2.7.11：给线路下拉 stretch=1（余宽优先给它，见上面的宽度说明）
        self.top_row.addWidget(self.top_lines_select, 1)
        self.top_row.addWidget(self.top_district, 0)
        self.top_row.addWidget(self.lbl_nursing, 0)
        self.top_row.addStretch(1)
        root.addLayout(self.top_row)

        # ★ v2.6.77：「线路 xxx」「ID xxx」副标题删除（对象保留不显示，
        #   show_station 里的 setText 引用零改动）。
        self.subtitle = QLabel("")
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet("color:#666;")
        self.subtitle.hide()

        # 可滚动字段区
        self.form_container = QWidget()
        # 用作用域选择器统管所有标签样式（跨列表单行里的 QLabel 也能命中）
        self.form_container.setObjectName("FormContainer")
        self.form_container.setStyleSheet("""
            QWidget#FormContainer QLabel { color: #666; font-size: 12px; }
        """)
        self.form_layout = QFormLayout(self.form_container)
        self.form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        self.form_layout.setFormAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form_container)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, 1)

        # 按钮区 ★ v2.6.77：「弹窗编辑 / 删除 / 取消 / 保存」四个按钮删除
        #   （改动靠切站/关窗的 flush_pending 自动保存兜底）。对象保留不挂布局，
        #   _set_enabled_buttons / 信号连接零改动。
        self.btn_delete = QPushButton("🗑 删除")
        self.btn_delete.setStyleSheet("color:#c0392b;")
        self.btn_more = QPushButton("↗ 弹窗编辑")
        self.btn_cancel = QPushButton("取消")
        self.btn_save = QPushButton("💾 保存")
        self.btn_save.setStyleSheet(
            "QPushButton{background:#1976d2;color:white;padding:6px 12px;border-radius:4px;}"
            "QPushButton:hover{background:#1565c0;}"
        )
        self.btn_delete.hide()
        self.btn_more.hide()
        self.btn_cancel.hide()
        self.btn_save.hide()

        # 信号连接
        self.btn_save.clicked.connect(self._on_save)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_more.clicked.connect(self._on_edit_in_dialog)
        self.btn_delete.clicked.connect(self._on_delete)

        self._set_enabled_buttons(False)
        self.show_empty_state()

    # ------------------------------------------------------------
    # 状态显示
    # ------------------------------------------------------------
    def set_view_mode(self, on: bool) -> None:
        """★ v2.7.14：看图模式下**站名不许改**。

        用户原话：「看图模式只能对文字类的进行修改（详细信息中的文字），
        即修改后不会影响主图显示的文字」⇒ 站名是画在主图上的（改了图就
        得重烘），所以看图模式下把它置灰只读；出入口 / 首末班 / 简介这些
        不显示在主图上的字照旧能改。
        """
        self.title.setReadOnly(bool(on))
        self.title.setStyleSheet(
            'QLineEdit[readOnly="true"]{background:#F0F2F5;color:#5A5A5A;}' if on
            else "")

    def show_empty_state(self):
        self._clear_form()
        self.title.setText("")
        self.title.setPlaceholderText("未选中站点")
        self.title.setEnabled(False)
        self.subtitle.setText("💡 单击地图上的站点查看/编辑；\n双击可弹出大窗口；\n地图空白处双击也能新增站点。")
        self.subtitle.setStyleSheet("color:#888; font-size:11px;")
        self._set_enabled_buttons(False)
        # v2.6.79：没选中站点 → 图片条 / 顶部下拉一起收起来
        self.img_scroll.hide()
        self.top_lines_select.hide()
        self.top_district.hide()
        # ★ v2.7.0：母婴室奶嘴标记也一起收起来
        try:
            self.lbl_nursing.hide()
        except Exception:
            pass

    # ------------------------------------------------------------
    # ★ v2.6.57：「改了字没点保存」的兜底
    # ------------------------------------------------------------
    def _is_dirty(self) -> bool:
        """当前表单里有没有"改了但没点保存"的内容（判定口径见 `_norm`）。"""
        if self._flushing:
            return False
        sid = self._current_station_id
        if not sid:
            return False
        data = get_data_manager().get_station(sid)
        # ★★ v2.6.57：这个站**已经不在了**（刚被改名换掉了主键 / 刚被删除）
        #   ⇒ 表单里那些值是**上一个站**的，绝不能拿旧 id 存回去 —— 实测会
        #   凭空造出一个只有 station_id 的**空壳记录**（改完名 stations 里
        #   同时留着新名和旧名两条）。改名与"未保存兜底"就是在这儿打架的。
        if not data:
            return False
        try:
            cur = self._collect()
        except Exception:
            return False
        for k, v in cur.items():
            dv = data.get(k)
            # ★ v2.6.79：images/cover 是面板自己维护的新字段 —— 旧数据里没有、
            #   面板也是空 ⇒ 同一个状态，别判脏（否则 381 个站全"脏"、
            #   每次切站都平白写盘）。
            if k in ("images", "cover") and not dv and not v:
                continue
            if _norm(dv) != _norm(v):
                return True
        return False

    def flush_pending(self) -> bool:
        """切走 / 关窗口前：把"改了没保存"的内容提交掉，别再静默丢弃。

        ★ 为什么是**自动保存**而不是弹窗追问：弹窗会打断操作（用户为"窗口
          抢焦点 / 被打断"投诉过三次），而且改了字的意图就是要它生效 ——
          真改错了 Ctrl+Z 能撤回来。
        ★ 站名为空时不自动存（那会存出一个没名字的站，想改回来更麻烦）。
        """
        if not AUTO_SAVE_PENDING:
            return False
        if not self._is_dirty():
            return False
        sid = self._current_station_id
        if not sid:
            return False
        try:
            payload = self._collect()
        except Exception:
            return False
        if not (payload.get("station_name") or "").strip():
            return False
        self._flushing = True
        try:
            self.save_requested.emit(sid, payload)
            self.auto_saved.emit(sid)
        finally:
            self._flushing = False
        return True

    def show_station(self, station_id: str):
        # ★ v2.6.57：先把"上一个站改了没保存"的改动兜住，再重建表单
        self.flush_pending()
        dm = get_data_manager()
        data = dm.get_station(station_id)
        if not data:
            self.show_empty_state()
            return

        self._current_station_id = station_id
        self._build_form(data)
        # ★ v2.6.8：多行框的高度要等**布局定型**才能量准（`fit_height` 在未布局
        #   时会直接放弃）。用 lambda 现取 `self._autofit` —— 表单每重建一次
        #   都会换一个新的组，闭包里写死引用会拿到已被 delete 的旧控件。
        QTimer.singleShot(0, lambda: getattr(self, "_autofit", None)
                          and self._autofit.sync())

        # ★ v2.6.79：图片条（旧的单张 cover 自动当作第一张）
        self._load_images(data)
        self.img_scroll.show()
        self.top_lines_select.show()
        self.top_district.show()

        name = data.get("station_name", "")
        self.title.setText(str(name))
        self.title.setPlaceholderText("")
        self.title.setEnabled(True)
        self._set_enabled_buttons(True)
        # ★★ v2.7.0：站名输入框宽度 = **刚好显示 4 个中文字**
        #   （用户：「右侧站点名称改为至少显示 4 个中文字符的输入框长度」）。
        #   用 QFontMetrics 实量当前字体，不写死像素 —— 换字号也不会挤掉字。
        if not self._title_w_locked:
            try:
                fm = QFontMetrics(self.title.font())
                need = fm.horizontalAdvance("国国国国") + 20   # 4 字净宽 + 光标/内边距
            except Exception:
                need = 68
            self.title.setFixedWidth(max(68, int(need)))
            self._title_w_locked = True
        # ★ v2.7.0：母婴室标记 —— facilities 里含「母婴室」才显示（奶嘴图标）
        try:
            _fac = str(data.get("facilities") or "")
            self.lbl_nursing.setVisible("母婴室" in _fac)
        except Exception:
            self.lbl_nursing.hide()

    def _emit_locate(self):
        """★ v2.6.91：点 🎯 —— 跳转到当前站（同搜索定位的效果）。"""
        if self._current_station_id:
            self.locate_requested.emit(self._current_station_id)

    # ------------------------------------------------------------
    # 尺寸变化：多行框要重算高度（窗口变宽 ⇒ 换行位置变了）
    # ------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        af = getattr(self, "_autofit", None)
        if af is not None:
            af.sync()

    def eventFilter(self, obj, ev):
        """站名输入框：**进焦点靠左、失焦居中**（v2.7.11）。

        ★ 用户原话「站点名称尽量居中显示，点击修改后再从左往右显示」。
        ★ 只认 Enter/Leave 那类会拖慢打字的事件没关系 —— 这里只处理
          FocusIn / FocusOut 两个事件，开销可以忽略。
        """
        if obj is getattr(self, "title", None):
            t = ev.type()
            if t == QEvent.FocusIn:
                self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            elif t == QEvent.FocusOut:
                self.title.setAlignment(Qt.AlignCenter)
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------
    # 表单构建
    # ------------------------------------------------------------
    @staticmethod
    def _make_stacked(label_text, editor: QWidget,
                      head_widget: QWidget = None) -> QWidget:
        """把一个「标签 + 输入框」竖着摞起来，整行宽（标签在上、输入框在下）。

        ★ v2.6.8：实现搬到 `ui/form_rows.py`（与编辑弹窗同一份）。
        ★ `head_widget`：挂在这一行**标题右侧**的别的字段的输入框。
        """
        return make_stacked(label_text, editor, head_widget)

    @staticmethod
    def _make_inline_row(label_text: str, editor: QWidget) -> QWidget:
        """「文字在左、输入框占满右边」的**单行**行（v2.6.5，与弹窗同形态）。

           设施    [ 卫生间、电梯、母婴室                    ]

        ★ 标签要给**固定宽度**，不然各字段标签宽度不一样，
          所有输入框的左边缘就参差不齐（一列内容看着是歪的）。
        """
        return make_inline_row(label_text, editor, PANEL_INLINE_LABEL_W)

    def _clear_form(self):
        # 用 removeRow 逐行清（QFormLayout 的官方接口）。
        # 注意别用 takeAt(0) 数着取：多行字段是"整行占满"的跨列排法，
        # 一行只有 1 个 item，按 item 下标循环会跟行数对不上。
        while self.form_layout.rowCount():
            self.form_layout.removeRow(0)
        self._widgets.clear()
        # ★ removeRow 会把整行控件 delete 掉，缓存的引用必须清掉，
        #   否则下一次 `_collect()` 会拿到已被销毁的 C++ 对象（直接崩）。
        self._exits_widget = getattr(self, "_exits_widget", None)
        self._exits_widget = None
        # ★ v2.6.8：同一个道理 —— 自动拉伸组里存的是**旧控件的引用**，
        #   切换站点后旧控件已经被 delete，sync() 一碰就是野指针。重新开一个。
        self._autofit = AutoFitGroup(min_h=PANEL_AUTOFIT_MIN_H)

    # ------------------------------------------------------------
    @staticmethod
    def _make_table(fields: list, editors: list) -> QWidget:
        """**横向并排的一组字段**，全部挤在**同一行**里（v2.4.17）。

        形态：`文字 | 控件 | 文字 | 控件`，全部垂直居中。
        与 `EditDialog._make_table` 同一做法
        （QFormLayout 一行装不下两组字段，用 QGridLayout 小容器整行占满）。
        """
        box = QWidget()
        g = QGridLayout(box)
        g.setSizeConstraint(QLayout.SetFixedSize)   # 见 EditDialog 同名方法的注释
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(6)                   # 组内"文字 ⇄ 控件"贴紧
        g.setVerticalSpacing(0)

        col = 0
        for i, (fld, ed) in enumerate(zip(fields, editors)):
            if i:
                # 两组之间的间隔（面板窄，间隔比弹窗小一点）
                g.setColumnMinimumWidth(col, PANEL_PAIR_GAP)
                g.setColumnStretch(col, 0)
                col += 1
            g.addWidget(QLabel(fld.get("label", fld["key"])), 0, col, Qt.AlignVCenter)
            col += 1
            if fld.get("type") == "bool":
                ed.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                g.addWidget(ed, 0, col, Qt.AlignLeft | Qt.AlignVCenter)
            else:
                if isinstance(ed, QLineEdit) and not ed.maximumWidth() < 16777215:
                    ed.setFixedWidth(PANEL_LINE_EDIT_WIDTH)
                g.addWidget(ed, 0, col, Qt.AlignVCenter)
            col += 1
        return box

    def _build_form(self, data: Dict):
        self._clear_form()
        lines = get_data_manager().all_lines()

        # v2.4.16：schema 里声明了 `row_with` 的字段要并成一行
        hrows: list = []
        _used: set = set()
        for field in EDITABLE_FIELDS:
            k = field["key"]
            if k in _used or not field.get("row_with"):
                continue
            mate = next((f for f in EDITABLE_FIELDS
                         if f["key"] == field["row_with"]), None)
            if mate is None:
                continue
            # 顺序按 schema 里的先后（见 EditDialog._hrow_fields 的注释）
            pair = sorted([field, mate],
                          key=lambda f: [x["key"] for x in EDITABLE_FIELDS].index(f["key"]))
            hrows.append(pair)
            _used.update((k, mate["key"]))
        hrow_keys = {f["key"] for row in hrows for f in row}

        # ---------------- 第一遍：把所有控件造出来 ----------------
        # ★ v2.4.16 必须分两遍：并排行里的两个控件都得到齐了才能挂，
        #   边遍历边挂的话，轮到并排行时第二个成员还没造出来 → 整行被跳过、
        #   字段直接消失（EditDialog 那边实测踩过同样坑）。
        editors: Dict[str, QWidget] = {}
        rows_v: Dict[str, QWidget] = {}       # None ⇒ 用 addRow(label, widget)
        rows_v_w: Dict[str, QWidget] = {}

        for field in EDITABLE_FIELDS:
            key = field["key"]
            # ★ v2.7.0：界面隐藏字段（v2.7.4 起只剩「设施」）—— 不生成控件。
            #   拿不到控件 ⇒ `_collect()` 不收这个键 ⇒ 合并写入保住原数据。
            # ★ v2.7.4：「出入口信息」不在这个集合里了 —— 它改成**只读展示**
            #   （`READONLY_UI_FIELDS`），控件照建、内容照显示，但不回写。
            if key in HIDDEN_UI_FIELDS:
                continue
            # ★ v2.7.5：`no_label` ⇒ **不画标题文字**（用户：「删除文字
            #   '出入口信息'」）。传 None 给 make_stacked，标题行整个不建。
            label = None if field.get("no_label") else field.get("label", key)
            t = field.get("type", "text")
            value = data.get(key, "")
            pending = key in hrow_keys

            if key == "station_name":
                # ★ v2.6.77：站点名称 = 面板最上方的输入框（self.title），
                #   表单里不再重复出「站点名称 [输入框]」行。
                self._widgets[key] = self.title
                editors[key] = self.title
                continue

            if key == "lines":
                # ★ v2.6.79：所属线路 = 面板顶部的常驻下拉（无「所属线路」标签），
                #   这里只登记 + 刷值，不再生成表单行。
                self._widgets[key] = self.top_lines_select
                editors[key] = self.top_lines_select
                self.top_lines_select.set_selected(value or [])
                continue

            if key == "district":
                # ★ v2.6.79：所属区 = 面板顶部的常驻下拉（无标签）。
                self._widgets[key] = self.top_district
                editors[key] = self.top_district
                _i = self.top_district.findData(str(value or ""))
                self.top_district.setCurrentIndex(_i if _i >= 0 else 0)
                continue

            if t == "text":
                w = QLineEdit()
                if field.get("placeholder"):
                    w.setPlaceholderText(field["placeholder"])
                w.setText(str(value) if value is not None else "")
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    rows_v[key] = None
                    rows_v_w[key] = w

            elif t == "multiline" and key == EXITS_KEY:
                # v2.6.5：出入口改成和弹窗一样的「编号 + 内容」两栏
                # （编号独立出去，"出入口"三字不再出现）。
                # ★ v2.7.5：编号升级成**按钮**（点了才能改编号），详细信息是
                #   **输入框**（可编辑）；标题文字「出入口信息」已按用户要求删掉
                #   （schema 里 `no_label: True`）。
                #   v2.7.4 那版"只读展示"作废 —— 用户要的是能改，不是只能看。
                w = ExitsEditor(value)
                self._exits_widget = w
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    rows_v[key] = self._make_stacked(label, w)
                continue

            elif t == "multiline" and key == TIMETABLE_KEY:
                # v2.6.5：首末班车改成和弹窗一样的表格。
                # ★ 面板可用宽只有 338px，完整表格要 454px ⇒ 必须用 **compact**。
                # v2.6.7：同弹窗 —— 日期类型下拉顶替「首末班车」标签。
                w = TimetableEditor(value, compact=True)
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    # ★ v2.6.8：日期下拉已搬进表格自己的表头行，这里只挂表格
                    rows_v[key] = w
                continue

            elif t == "multiline" and field.get("same_row"):
                # v2.6.5：**只有一行高**（与弹窗一致）。
                # v2.6.8：不显示"设施"两个字 —— 挂到「出入口信息」那行标题右侧。
                w = QLineEdit()
                w.setMinimumHeight(30)
                if field.get("placeholder"):
                    w.setPlaceholderText(field["placeholder"])
                w.setText(str(value) if value is not None else "")
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    # 先备好"自己占一行"，inject 成功会被摘走
                    rows_v[key] = self._make_inline_row(label, w)
                continue

            elif t == "multiline":
                w = QPlainTextEdit()
                if field.get("placeholder"):
                    w.setPlaceholderText(field["placeholder"])
                w.setPlainText(str(value) if value is not None else "")
                # ★ v2.6.8：高度自动拉伸（原来写死 60~160，长文字只能内部滚）
                self._autofit.add(w, min_h=PANEL_AUTOFIT_MIN_H)
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    # 多行字段：标签在上、输入框在下、整行宽（与 EditDialog 一致）
                    # ★ v2.6.77：「简介」两个字删掉（label=None ⇒ 无标签行）
                    rows_v[key] = self._make_stacked(
                        None if key == "description" else label, w)

            elif t == "bool":
                w = QCheckBox()
                w.setChecked(bool(value))
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    # 让 bool 标签在左边紧贴，避免占满一行
                    container = QWidget()
                    h = QHBoxLayout(container)
                    h.setContentsMargins(0, 0, 0, 0)
                    h.addWidget(w)
                    h.addStretch()
                    rows_v[key] = container

            elif t == "lines":
                # 下拉多选（与 EditDialog 用同一个控件，保持两处手感一致）
                w = LinesSelect(lines, value or [])
                self._widgets[key] = w
                editors[key] = w
                rows_v[key] = None
                rows_v_w[key] = w

        # -------- 第一遍半：`head_with` 的字段挂进目标行的标题右侧（v2.6.8）--------
        # 与 EditDialog 同一份逻辑（设施 → 出入口信息那一行），失败则退回自己占一行。
        _injected: set = set()
        for field in EDITABLE_FIELDS:
            tgt = field.get("head_with")
            if not tgt:
                continue
            w = editors.get(field["key"])
            box = rows_v.get(tgt)
            if w is not None and box is not None and inject_head(box, w):
                _injected.add(field["key"])
                rows_v.pop(field["key"], None)

        # ---------------- 第二遍：按 schema 顺序挂行 ----------------
        # 规则：并排行在**它第一个成员**在 schema 里的位置出场
        emitted: set = set()
        for field in EDITABLE_FIELDS:
            key = field["key"]
            if key in emitted or key in _injected:
                continue
            row = next((r for r in hrows if any(f["key"] == key for f in r)), None)
            if row is not None:
                emitted.update(f["key"] for f in row)
                eds = [editors.get(f["key"]) for f in row]
                if any(e is None for e in eds):
                    continue                       # 有空缺就整行放弃
                self.form_layout.addRow(self._make_table(row, eds))
                continue
            emitted.add(key)
            if key not in editors or key not in rows_v:
                continue
            box = rows_v[key]
            if box is None:
                self.form_layout.addRow(field.get("label", key), rows_v_w[key])
            else:
                self.form_layout.addRow(box)

    # ------------------------------------------------------------
    # 取值 / 保存
    # ------------------------------------------------------------
    def _collect(self) -> Dict:
        # ★ v2.6.5：**按控件类型分派**，不再按 `type == "multiline"` 一刀切。
        #   面板里同一个 type 现在有三种控件：
        #     · exits     → ExitsEditor（`text()` 拼装）
        #     · timetable → TimetableEditor（`text()` 拼装）
        #     · facilities(same_row) → 已经换成 QLineEdit
        #     · 其余多行   → QPlainTextEdit
        #   按 type 分派会把前三种全当 QPlainTextEdit 处理（`.toPlainText()`
        #   不存在 → AttributeError，或者更糟：静默拿到错的接口）。
        out: Dict = {}
        for field in EDITABLE_FIELDS:
            key = field["key"]
            t = field.get("type", "text")
            # ★★ v2.7.4：**只读展示字段一律不回写**（当前只有「出入口信息」）。
            #   两道保险：① 控件本身是只读的；② 这里直接不收 ⇒ payload 里没有这个键
            #   ⇒ `upsert_station`（合并写入）保留 stations.json 里的原值。
            #   就算只读控件拼回文本时格式有细微差异，也绝无可能写进数据。
            if key in READONLY_UI_FIELDS:
                continue
            w = self._widgets.get(key)
            if w is None:
                continue
            if isinstance(w, (ExitsEditor, TimetableEditor)):
                out[key] = w.text()
            elif isinstance(w, QPlainTextEdit):
                out[key] = w.toPlainText().strip()
            elif isinstance(w, QLineEdit):
                out[key] = w.text().strip()
            elif isinstance(w, QComboBox):
                # v2.6.79：下拉字段的值 = currentData（存选项 value，与弹窗一致）
                out[key] = str(w.currentData() or "")
            elif t == "bool":
                out[key] = w.isChecked()
            elif t == "lines":
                if hasattr(w, "selected_ids"):
                    out[key] = list(w.selected_ids())
                elif isinstance(w, list):        # 兼容旧的多选框实现
                    out[key] = [cb.property("line_id") for cb in w if cb.isChecked()]
                else:
                    out[key] = []
        # ★ v2.6.79：多图由图片条维护（不在 EDITABLE_FIELDS 里）。
        #   cover 永远 = 第一张（兼容旧读路径）。
        _imgs = list(getattr(self, "_images", []) or [])
        out["images"] = _imgs
        out["cover"] = _imgs[0] if _imgs else ""
        # ★ v2.6.6：`is_transfer` 勾选框已删，改由「所属线路」推导
        #   （与编辑弹窗共用 `core.schema.derive_is_transfer`，只有一份实现）。
        return derive_is_transfer(out)

    def _on_save(self):
        if not self._current_station_id:
            return
        payload = self._collect()
        # 把必填字段做个最小校验
        if not payload.get("station_name"):
            # 在标题附近红字提示
            self.subtitle.setText("⚠️ 站点名称不能为空")
            self.subtitle.setStyleSheet("color:#c0392b;")
            return
        self.save_requested.emit(self._current_station_id, payload)

    def _on_cancel(self):
        if self._current_station_id:
            self.show_station(self._current_station_id)  # 重新加载、丢弃改动

    def _on_edit_in_dialog(self):
        if self._current_station_id:
            self.edit_in_dialog_requested.emit(self._current_station_id)

    def _on_delete(self):
        if self._current_station_id:
            from PySide6.QtWidgets import QMessageBox
            r = QMessageBox.question(
                self, "确认删除",
                "删除当前站点？此操作只删除软件内记录。",
                QMessageBox.Yes | QMessageBox.No
            )
            if r == QMessageBox.Yes:
                self.delete_requested.emit(self._current_station_id)

    def _set_enabled_buttons(self, enabled: bool):
        self.btn_save.setEnabled(enabled)
        self.btn_cancel.setEnabled(enabled)
        self.btn_more.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)

    # ------------------------------------------------------------
    # ★ v2.6.79：站点图片条（多图）
    # ------------------------------------------------------------
    PANEL_IMAGE_FILTER = ("图片 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;"
                          "所有文件 (*.*)")
    IMG_TILE = 84                      # 缩略图边长（条高 104 = 84 + 边距）

    def _load_images(self, data: Dict) -> None:
        """从站点数据取图片列表（images 优先，旧 cover 兜底为第一张）。"""
        dm = get_data_manager()
        names = data.get("images")
        if isinstance(names, str):
            names = [names]
        self._images = [str(n) for n in (names or [])]
        if not self._images:
            cov = str(data.get("cover") or "").strip()
            if cov:
                self._images = [cov]
        # 过滤掉文件已不存在的引用，别把死链画进界面
        self._images = [n for n in self._images if dm.cover_path(n)]
        self._refresh_images_strip()

    def _refresh_images_strip(self) -> None:
        row = getattr(self, "img_row", None)
        if row is None:
            return
        while row.count():
            it = row.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        dm = get_data_manager()
        from ui.widgets import make_cover_icon, make_add_image_icon
        tile = self.IMG_TILE
        for i, name in enumerate(self._images):
            p = dm.cover_path(name)
            if not p:
                continue
            btn = QToolButton()
            btn.setFixedSize(tile, tile)
            btn.setIconSize(QSize(tile - 10, tile - 10))
            btn.setIcon(make_cover_icon(p, tile - 10))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QToolButton { border: 1px solid #d5d9e0; border-radius: 6px;
                              background: #fff; }
                QToolButton:hover { border-color: #1976d2; }
            """)
            btn.setToolTip(f"{name}\n左键看大图，右键移除")
            btn.clicked.connect(lambda _=False, pp=p: self._view_image(pp))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, idx=i: self._on_img_menu(pos, idx))
            row.addWidget(btn, 0, Qt.AlignVCenter)
        # ＋ 添加格子
        add_btn = QToolButton()
        add_btn.setFixedSize(tile, tile)
        add_btn.setIcon(make_add_image_icon(tile - 10))
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setStyleSheet("""
            QToolButton { border: 1px dashed #b6bcc6; border-radius: 6px;
                          background: #fbfcfe; }
            QToolButton:hover { border-color: #1976d2; background: #f0f6ff; }
        """)
        add_btn.setToolTip("添加图片（可按住 Ctrl 多选）")
        add_btn.clicked.connect(self._on_add_images)
        row.addWidget(add_btn, 0, Qt.AlignVCenter)
        row.addStretch(1)

    def _view_image(self, path) -> None:
        from ui.image_viewer import show_image_viewer
        show_image_viewer(self, path)

    def _on_add_images(self) -> None:
        sid = self._current_station_id
        if not sid:
            return
        dm = get_data_manager()
        paths, _ = QFileDialog.getOpenFileNames(
            self, "添加图片（可多选）", str(Path.home()), self.PANEL_IMAGE_FILTER)
        if not paths:
            return
        added = False
        for p in paths:
            try:
                self._images.append(dm.import_image(sid, p))
                added = True
            except Exception as e:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "图片导入失败", str(e))
        if added:
            self._refresh_images_strip()
            self._on_save()          # 走面板统一保存路径（images 进 payload）

    def _on_img_menu(self, pos, idx: int) -> None:
        menu = QMenu(self)
        act_view = menu.addAction("🔍 查看大图")
        act_del = menu.addAction("✕ 移除此图")
        sender = self.sender()
        chosen = menu.exec(sender.mapToGlobal(pos) if sender else None)
        if chosen is act_view:
            dm = get_data_manager()
            if 0 <= idx < len(self._images):
                p = dm.cover_path(self._images[idx])
                if p:
                    self._view_image(p)
        elif chosen is act_del:
            if 0 <= idx < len(self._images):
                dm = get_data_manager()
                dm.remove_cover(self._images[idx])   # 直接删文件，别留孤儿
                self._images.pop(idx)
                self._refresh_images_strip()
                self._on_save()

    # ------------------------------------------------------------
    # API
    # ------------------------------------------------------------
    def current_station_id(self) -> str:
        return self._current_station_id
