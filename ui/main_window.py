"""
ui/main_window.py
========================
主窗口：

   ┌────────────────────────────────────────────────────────────────────┐
   │ 工具栏：新建站点(开关)  适配窗口  100%  保存  导入  关于        │
   ├──────────────────────────────────────────────────────┬─────────────┤
   │                                                      │  站点详情    │
   │                                                      │  (InfoPanel) │
   │                  地图视图 (MapView)                   │             │
   │                                                      │             │
   │                                                      │             │
   ├──────────────────────────────────────────────────────┴─────────────┤
   │ 状态栏：缩放比例  站点数  上次保存时间                                │
   └────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import os
import copy
import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QPoint, QTimer, QEvent, QSize, QRectF
from PySide6.QtGui import (
    QAction, QKeySequence, QShortcut, QIcon, QPixmap, QPainter, QColor,
    QBrush, QCursor, QPen, QPainterPath, QGuiApplication,
)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QToolBar, QStatusBar, QMessageBox, QFileDialog, QLabel, QLineEdit,
    QPushButton, QMenu,
)

# 项目内
from ui.map_view import MapView, load_badge_offsets, save_badge_offsets
from ui.info_panel import InfoPanel
from ui.edit_dialog import EditDialog
from ui.tooltip import HoverTip
from ui.legend_panel import LegendPanel
from ui.train_consist_card import TrainConsistCard
from ui.isolated_close_button import IsolatedCloseButton
from core.train_consist import consist_for
from ui.widgets import SearchSuggestPopup, SUGGEST_MAX_ROWS
from core.data_manager import get_data_manager, _frozen_or_dev_root as PROJECT_ROOT
from core.schema import EDITABLE_FIELDS, new_station_template


def read_text_file_smart(path) -> str:
    """
    按"猜编码"的方式把文本文件读进来。

    为什么要这么麻烦：用户拿到的导入 JSON 往往是从记事本另存出来的，
    而记事本在不同版本的"编码"下拉里会写出 **UTF-8 带 BOM**、甚至 **UTF-16**。
    原来这里写死 encoding="utf-8"，遇到带 BOM 的文件 json.load 会直接抛
    "Unexpected UTF-8 BOM"，用户看到一个完全不知所云的报错。
    现在：先看前两个字节判断 BOM，再退到 utf-8-sig / utf-8。
    """
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):          # UTF-16 LE / BE
        return raw.decode("utf-16")
    if raw[:3] == b"\xef\xbb\xbf":                     # UTF-8 BOM
        return raw.decode("utf-8-sig")
    for enc in ("utf-8", "gbk"):                       # 无 BOM：UTF-8 优先，兜底 GBK
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ★ v2.6.34：撤销栈深度。一份快照 ≈ 160KB（站点+线路+方块偏移），50 步不到 8MB。
UNDO_DEPTH = 50


BLUE_ON = QColor("#2E86FF")      # 锁定蓝（与缩放滑块手柄同色系）
GREY_OFF = QColor("#E8EDF2")     # 未锁：浅灰底（比纯白更能看出"两半"的分界）


class LockButton(QPushButton):
    """★ v2.7.1：🔒 双锁按钮 —— **按钮本身**分上下两半，各半独立变蓝。

    ★★ v2.7.0 那版做成了"图标里的锁体分上下两半"，用户说理解错了。
    用户原话：「我要求**按钮**分为上下两部分变蓝…… 锁定轨迹时上方变蓝，
    锁定文字时下方变蓝，全部锁定上下全部变蓝」。

    所以这里把 **按钮矩形** 切成上下两块背景：
        上半 = 轨迹锁（stations_locked）
        下半 = 文字锁（labels_locked）
    锁图标叠在中间，上下两半各用**对比色**重画一次
    （蓝底那半画白锁、灰底那半画深灰锁）⇒ 半锁时也不会有半截看不见。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._body = False            # 轨迹锁
        self._label = False           # 文字锁
        self.setFixedSize(38, 26)
        self.setCursor(Qt.PointingHandCursor)

    # ---- 状态 ----
    def lock_states(self):
        return (self._body, self._label)

    def set_lock_states(self, body: bool, label: bool) -> None:
        body, label = bool(body), bool(label)
        if (body, label) == (self._body, self._label):
            return
        self._body, self._label = body, label
        self.update()

    # ---- 自绘 ----
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.setClipPath(path)

        half = r.height() / 2.0
        top = QRectF(r.x(), r.y(), r.width(), half)
        bot = QRectF(r.x(), r.y() + half, r.width(), r.height() - half)
        p.fillRect(top, BLUE_ON if self._body else GREY_OFF)
        p.fillRect(bot, BLUE_ON if self._label else GREY_OFF)

        # 锁图标：上下两半分两次画，各取对比色
        for rect, on in ((top, self._body), (bot, self._label)):
            p.save()
            p.setClipRect(rect, Qt.IntersectClip)
            self._draw_lock(p, r, QColor("#FFFFFF") if on else QColor("#5A6B7D"))
            p.restore()

        p.setClipping(False)
        p.setPen(QPen(QColor("#B9C4CF"), 1))
        p.drawPath(path)
        p.end()

    @staticmethod
    def _draw_lock(p: QPainter, r: QRectF, color: QColor) -> None:
        """在 r 正中画一把小锁（锁梁半圆环 + 实心锁体）。"""
        s = min(r.width(), r.height()) * 0.66
        x = r.center().x() - s / 2.0
        y = r.center().y() - s / 2.0
        pen = QPen(color)
        pen.setWidthF(max(1.3, s * 0.13))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(x + s * 0.22, y + s * 0.02, s * 0.56, s * 0.55), 0, 180 * 16)
        p.setBrush(QBrush(color))
        p.drawRoundedRect(QRectF(x + s * 0.12, y + s * 0.50, s * 0.76, s * 0.46), 2, 2)


def _logo_icon(size: int = 22) -> QIcon:
    """★ v2.7.2：软件自己的 logo（assets/logo.png，源图 `D:\\网盘\\图片\\深圳地铁.png`）。

    开发态读 `源码/assets`；打包后读 `sys._MEIPASS/assets`（build_exe.py 已 --add-data）。
    ★ 取不到就返回**空 QIcon**并打印 —— 别静默吞掉，否则按钮变成一块空白，
    看着像"图标没做出来"而不是"文件没带上"。
    """
    try:
        from core.data_manager import _frozen_assets_dir
        p = Path(_frozen_assets_dir()) / "logo.png"
        if p.is_file():
            return QIcon(str(p))
        print("[logo] 未找到图标文件：", p)
    except Exception as e:
        print("[logo] 载入失败：", repr(e))
    return QIcon()


# ★ v2.7.13：左右面板改成"地图之上的浮层"之后的宽度常量（手感可调）
LEGEND_MIN_W = 160        # 左侧图例最窄
INFO_PANEL_MIN_W = 360    # 右侧详情面板最窄（里面表单挤不成样）
INFO_PANEL_MAX_W = 780    # 最宽（再按屏宽 55% 封顶，见 _overlay_width_cap）
MAP_MIN_VISIBLE = 320     # 两个浮层都开着时，地图至少露这么多 px
GRIP_W = 6                # ★ v2.7.16：拖宽把手宽度（px）。热区只有这么宽，
                          #   但它现在挂在最上层，谁也盖不住它


class _OverlayGrip(QWidget):
    """浮层靠地图那一侧的**拖宽把手**（v2.7.13，替代原来 splitter 的拖动条）。

    side="right"：把手在浮层**右**缘（左侧图例）—— 往右拖 = 变宽。
    side="left" ：把手在浮层**左**缘（右侧详情）—— 往左拖 = 变宽。
    只负责算出新宽度回调给主窗口，限幅在 `_layout_overlays` 里统一做。

    ★★ v2.7.16：把手的父控件是 **map_area**（跟浮层同级），不再是浮层自己。
      旧写法把手长在浮层里，被浮层的内容控件（InfoPanel 那一整块）盖住，
      鼠标事件先被内容吃掉 ⇒ 用户报的「光标贴到边缘了却不出现拉伸箭头」。
    """

    def __init__(self, parent, side: str, on_resize, min_w: int, get_w=None):
        super().__init__(parent)
        self._side = side
        self._on = on_resize
        self._min = int(min_w)
        self._get_w = get_w                 # 取"当前浮层宽度"的回调
        self._start_x = None
        self._start_w = 0
        self.setFixedWidth(GRIP_W)          # ★ v2.7.16：4 → 6px（原来太窄不好抓）
        self.setCursor(Qt.SplitHCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    def _cur_w(self) -> int:
        """当前被拖的那个浮层的宽度（★ 不能再用 parent().width() ——
        parent 现在是 map_area，它的宽度是整块地图，不是浮层宽度）。"""
        if self._get_w is not None:
            try:
                return int(self._get_w())
            except Exception:
                pass
        return int(self.parent().width())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start_x = event.globalPos().x()
            self._start_w = self._cur_w()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._start_x is None:
            return
        d = event.globalPos().x() - self._start_x
        w = self._start_w + (d if self._side == "right" else -d)
        self._on(int(max(w, self._min)))
        event.accept()

    def mouseReleaseEvent(self, event):
        self._start_x = None
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("深圳地铁线路图编辑器  v2.0")
        self.resize(1480, 900)
        # ★ v2.6.44：用户原话「如果不是必须不要把调试页面置顶，我还在使用电脑呢」。
        #   自动化（回归脚本 / 打包后自动打开）每次都弹一个 1480×900 窗口并**抢走
        #   焦点**，用户正在打字/看东西就被打断。
        #   设 `METROEDITOR_NO_ACTIVATE=1` ⇒ 窗口照常显示（能截图、能验收），
        #   但**不激活、不抢焦点**（Qt 的 WA_ShowWithoutActivating）。
        #   用户自己双击 exe 时不设这个变量 ⇒ 行为和以前一样，正常弹到前台。
        if os.environ.get("METROEDITOR_NO_ACTIVATE") == "1":
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self.dm = get_data_manager()

        # ------------------------------------------------------------------
        # ★★ v2.6.34：撤销 / 重做（Ctrl+Z / Ctrl+Y）
        #
        # 为什么用"整份快照"而不是给每个操作写一条 UndoCommand：
        #   这个软件能改数据的地方太多（拖站点、拖站名、拖线路号、编辑弹窗、
        #   批量导入、删除…），一条条写命令**必然会漏**，漏掉的那条在用户
        #   撤销时就会把数据搞得前后不一致。而三类文件加起来才 160KB，
        #   deepcopy 一遍 10ms 都不到，栈深 50 也就 8MB 内存 ——
        #   用"笨但一定对"的办法，换"绝不会漏操作"。
        #
        # 时机：`_save_data()` 是**唯一**的业务落盘口（顶上有注释要求），
        #   所以把"上一次落盘后的状态"压在它前面入栈即可 ——
        #   每次保存 = 一个操作 = 一步撤销。
        # ------------------------------------------------------------------
        self._undo_stack: list = []
        self._redo_stack: list = []
        self._snap_before = None      # "上一次落盘之后"的状态
        self._restoring = False       # 恢复期间不要再压栈

        # 悬浮提示
        self.tip = HoverTip(self)

        # 主布局 splitter：[图例] [地图] [信息面板]
        self.map_view = MapView()
        self.info_panel = InfoPanel()
        self.legend_panel = LegendPanel()

        # ★★ v2.6.89：右侧详情面板外面包一层容器。
        #   ★ v2.6.91：「»/«」按钮从面板头部挪到**主工具栏最右**
        #   （用户：「隐藏按钮位置错了，要求在'豪宅'按钮这行的右侧」——
        #     豪宅 = 工具栏最后一个图标开关，按钮放它同一行最右）。
        #   ★★ v2.7.3：收起时**整个容器一起藏掉**（0 宽，不是留 26px 细条）。
        #     那条细条当年是为了放面板头部的 «/« 按钮；按钮早就搬到工具栏了，
        #     细条只剩一条碍眼的空边 —— 用户：「点击收起后并没有完全收起」。
        self.info_wrap = QWidget()
        _wv = QVBoxLayout(self.info_wrap)
        _wv.setContentsMargins(0, 0, 0, 0)
        _wv.setSpacing(0)
        _wv.addWidget(self.info_panel)

        # ★★ v2.7.13：三栏 QSplitter **整个撤掉**，改成"地图铺满 + 左右面板
        #   做浮层盖在地图上方"。
        #   用户原话「单击左侧(图例)/右侧(站点详情面板)会立即弹窗，把弹窗改为
        #   覆盖下方的图，而不是现在把图往中间挤」—— 旧方案里面板一出现就从
        #   splitter 分走宽度 ⇒ 地图被挤窄、内容跟着重排往中间缩。
        #   现在地图视口宽度**恒定不变**，面板只是叠在它上面（遮住哪块是哪块）。
        self.map_area = QWidget()
        self.map_area.setObjectName("MapArea")
        _ma = QVBoxLayout(self.map_area)
        _ma.setContentsMargins(0, 0, 0, 0)
        _ma.setSpacing(0)
        _ma.addWidget(self.map_view)
        self.setCentralWidget(self.map_area)

        # 两个面板不再进布局：改成 map_area 的**子部件**，几何由 _layout_overlays
        # 绝对定位（盖在地图上，raise_ 置顶）。setParent 之后默认是隐藏的，
        # 图例要显式 show（详情面板按 v2.7.1 仍默认收起）。
        self.legend_panel.setParent(self.map_area)
        self.info_wrap.setParent(self.map_area)
        self.legend_panel.show()
        # ★ v2.6.89：图例 / 详情面板的"记忆宽度"初值
        self._legend_w = 200
        # ★ v2.7.18：右侧面板宽度从设置里读（拖过边缘 ⇒ 记的是你拖的宽度）
        self._info_w = self._saved_info_w()
        # ★ 浮层边缘的拖宽把手（替代原来 splitter 的拖动条）
        self._build_overlay_grips()

        # 工具栏 + 状态栏
        self._build_toolbar()
        self._build_statusbar()
        self._build_fullscreen()

        # 信号连接
        self._wire_signals()

        # 载入线路 + 站点
        self.map_view.rebuild_lines()
        self.map_view.reload_stations(self.dm.all_stations())
        self.legend_panel.set_lines(self.dm.all_lines(), self.dm.all_stations())
        self._refresh_status()

        # ★ v2.7.0：启动即**锁定轨迹**（用户：「每次进入软件默认锁定线路轨迹」），
        #   文字默认不锁 ⇒ 按钮此刻显示"上半蓝"。
        self._apply_lock_states(True, False)

        # ★ v2.7.1：搜索框挂在左侧图例顶部（1 号线上方）
        self._build_search_box()

        # ★ v2.7.1：首次打开**不显示**右侧详情面板（用户要求）。
        #   点站点 / 用右键菜单里的"显示站点详情面板"都能把它叫出来。
        self.info_panel.hide()
        self.info_wrap.hide()          # ★ v2.7.3：容器一起藏 ⇒ 启动就"完全收起"
        # ★ v2.7.2：按钮不再写文字（只显示 logo 图），状态靠 tooltip 说明
        self.btn_info_toggle.setToolTip("显示站点详情面板")
        # ★★ 浮层几何要等窗口 **show 之后** 再摆：`__init__` 里 map_area 还没
        #   拿到真实宽度，此刻定位会算出怪值（旧版实测图例被摆到 y = -871，
        #   整个左栏跑到窗口上方去了）。所以挂到首次 showEvent 再做。
        self._pending_overlay_layout = True

        # ★★ v2.7.33：把"两个浮层都开着时，地图至少露 MAP_MIN_VISIBLE"这条承诺
        #   **做在窗口这一层**。
        #   原来它只写在 `_layout_overlays()` 的注释里：那里先按比例收缩，紧接着
        #   又用 LEGEND_MIN_W / INFO_PANEL_MIN_W 把宽度**顶回去**；而控件自己还
        #   各自带 minimumWidth（图例 196 / 详情 480），Qt 会把 setGeometry 传进去
        #   的宽度**再顶一次**。偏偏主窗口没有最小宽度、可以随便拉小 ⇒ 实测：
        #       窗口 900px → 地图只剩 306px（承诺是 320）
        #       窗口 600px → 只剩 44px
        #       窗口 400px → -156px（浮层左右**完全盖满**，看不见也点不到图）
        #   ⇒ 窗口最小宽度 = 图例下限 + 详情下限 + 地图要留的那 320px。
        #   正常尺寸（≥1280）下一行都不变，只是把"拉不到那么窄"这件事定死。
        self.setMinimumWidth(
            self.legend_panel.minimumWidth()
            + self.info_panel.minimumWidth()
            + MAP_MIN_VISIBLE)

        # 右下角车厢编组卡片（只在"单独显示某条线路"时出现）
        # ★ 挂在 map_view.viewport() 下：它是"地图之上的界面层"，
        #   缩放动画那层合成快照盖住的是地图，而它在快照之上，不会被卷进去缩放。
        self.consist_card = TrainConsistCard(self.map_view.viewport())
        self.map_view.register_chrome(self.consist_card)
        self._reposition_consist_card()

        # 右上角退出「只看这一条线」的**红色大 ✕**（v2.6.4）
        # ★ 原来这个入口是右下角卡片上的一行蓝字（「✕ 显示全部」），太不显眼。
        #   挂 "tr" 角落由 `MapView._layout_chrome` 在每次绘制前用当前视口尺寸校正。
        self.isolated_close = IsolatedCloseButton(self.map_view.viewport())
        self.isolated_close.clicked.connect(self._exit_isolation)
        self.map_view.register_chrome(self.isolated_close, "tr")

        # 让地图拿到初始焦点，便于立刻用键盘
        self.map_view.setFocus()

        # 启用悬浮检测
        self.map_view.setMouseTracking(True)
        self.map_view.viewport().setMouseTracking(True)
        self.map_view.viewport().installEventFilter(self)

        # 自动保存提示
        self._dirty = False

        # ★ v2.6.34：把"刚启动时的状态"当撤销栈的基线 —— 不先垫这一层的话，
        #   启动后的**第一个**操作会因为栈里什么都没有而撤不回去。
        self._snap_before = self._snapshot()

    # ------------------------------------------------------------------
    # 工具栏 / 状态栏
    # ------------------------------------------------------------------
    def _build_toolbar(self):
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        tb.setIconSize(tb.iconSize())
        # ★ v2.7.1：工具栏**不吃右键**（原来右键工具栏会弹"打开/关闭主工具栏"）。
        #   用户要求改到**地图右键菜单**里（见 _on_map_context_menu）。
        tb.setContextMenuPolicy(Qt.NoContextMenu)
        self.addToolBar(tb)
        self.toolbar = tb

        # ★★ v2.7.1：搜索框搬到**左侧线路图例顶部**（1 号线上方，用户指定）。
        #   工具栏这边不再放搜索框；下面只建好控件，挂载见 _build_search_box()。
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索站点名…")
        self.search_box.setMinimumWidth(110)
        self.search_box.returnPressed.connect(self._on_search)
        # v2.5.0：边打字边在下面列候选
        self.search_box.textChanged.connect(self._on_search_text_changed)
        self.search_box.installEventFilter(self)      # ↑↓ 选项 / Enter 选中 / Esc 关

        # ★★ v2.6.89：「定位」按钮删除（用户：按回车或点下拉候选即可，按钮多余）。
        #   returnPressed → _on_search、候选 picked → _on_suggest_picked 两条路都在，
        #   行为一点不缺。

        # ★★ v2.6.89：左侧线路图例 显示/隐藏 开关 —— 用户指定放在 🔒 左侧。
        # ★ v2.7.2：按钮图标 = **软件自己的 logo**（用户：「改为和软件相同的logo」）
        self.btn_legend_toggle = QPushButton()
        self.btn_legend_toggle.setFixedWidth(38)
        self.btn_legend_toggle.setIcon(_logo_icon(22))
        self.btn_legend_toggle.setIconSize(QSize(22, 22))
        self.btn_legend_toggle.setCheckable(True)
        self.btn_legend_toggle.setChecked(True)
        self.btn_legend_toggle.setToolTip("显示/隐藏左侧线路图例")
        self.btn_legend_toggle.toggled.connect(self._on_toggle_legend)
        tb.addWidget(self.btn_legend_toggle)

        # ★★ v2.6.89：🔒 锁定开关 —— 锁住后站点圆点 / 站名文字都拖不动
        #   （用户原话「点击后则不可以拖动站点位置、站点文字位置」），
        #   再点一次解锁。放在搜索框右侧（用户澄清：「出入口」说错了，
        #   实指站点检索输入框右侧）。
        # ★★ v2.7.0：🔒 双锁按钮 ——
        #   左键 = 一键全锁 / 全解（用户选定）；
        #   右键 = 菜单里单独勾选「锁定轨迹」「锁定文字」；
        #   ★ v2.7.1：图标改为**按钮上下两半各自变蓝**（见 LockButton）。
        #   ★ 启动默认**锁定轨迹**（用户：「每次进入软件默认锁定线路轨迹」）——
        #     真正的置位在 map_view 建好之后（见 __init__ 尾部 _apply_lock_states）。
        self.btn_lock = LockButton()
        self.btn_lock.setToolTip("锁定：左键一键全锁/全解 · 右键单独勾选轨迹/文字")
        self.btn_lock.setCursor(Qt.PointingHandCursor)
        self.btn_lock.clicked.connect(self._on_lock_click)
        self.btn_lock.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_lock.customContextMenuRequested.connect(self._on_lock_menu)
        tb.addWidget(self.btn_lock)

        # 候选面板（独立顶层窗口，挂在主窗口下）
        # ★ v2.5.1：把搜索框交给它做"按键转发目标"。
        #   面板是 Qt.Popup，按键会先落到面板上；不转发的话，
        #   面板一弹出来，用户接着打的字/退格/上下键全被吃掉。
        self.search_popup = SearchSuggestPopup(self, key_target=self.search_box)
        self.search_popup.picked.connect(self._on_suggest_picked)

        tb.addSeparator()

        # ★ v2.6.35：官方原图垫底 —— 用来对照着手动调站点/线路。
        #   ★ v2.7.2：它不在用户重排的那批按钮里，保持原位（图标四开关之前）。
        self.act_underlay = QAction("🖼 原图对照", self)
        self.act_underlay.setShortcut(QKeySequence("Ctrl+B"))
        self.act_underlay.setCheckable(True)
        self.act_underlay.triggered.connect(self._on_toggle_underlay)
        tb.addAction(self.act_underlay)

        # ★ v2.6.79：图标四开关（商场 / 交通 / 酒店 / **豪宅**）——
        #   ★★ v2.7.2：用户口中的「豪宅」按钮就在这一行；重排后它是**分界**：
        #      它右边依次排「编辑模式」和 9 个编辑类按钮。
        tb.addSeparator()
        tb.addWidget(self.map_view.icon_panel)
        # 缩放双滑块常驻**左栏（线路图例）底部**（v2.6.79，跟工具栏无关，放这儿只为上下文）
        self.legend_panel.add_persistent_bottom(self.map_view.scale_panel)

        # ★★ v2.7.2：「编辑模式」+ 编辑类按钮 —— **全部紧跟在豪宅那一行之后**。
        #   ★★ v2.7.3：用户授权「按你认为有必要存在的进行删减/排序/增添」，定案：
        #       编辑模式 → 新建站点 → 添加模式 → **删除站点** → 保存 → 撤销 → 重做
        #       → 吸附到原图 → 偏差检查
        #     删（改挂 Ctrl+Shift 快捷键，**功能不丢**，只是不再常驻）：
        #       · 自动描线 —— 全图重描会**覆盖手工修好的数据**，不该放在手边
        #       · 批量导入 / 导出当前数据 —— 一次性数据迁移才用得上
        #     增：删除站点 —— 编辑模式下居然没有"删站"入口，以前只能去右键菜单找。
        #   默认关：这些按钮全部隐藏，点开「编辑模式」才显示。
        # ★★ v2.7.14：这个按钮**位置恒定** —— 永远排在所有编辑按钮的**右边**
        #   （用户原话：「按钮位置不改变，按钮左侧弹出相关的编辑按钮」）。
        #   文字 = 目标模式：当前看图 ⇒ 写「✎ 编辑模式」（点它去编辑）。
        self.act_edit_mode = QAction("✎ 编辑模式", self)
        self.act_edit_mode.setCheckable(True)
        self.act_edit_mode.setToolTip("编辑模式 ⇄ 看图模式（看图模式 = 整张图变一张照片，丝滑）")
        self.act_edit_mode.triggered.connect(self._on_toggle_edit_mode)
        # ★ 注意：这里**先不 addAction** —— 要等编辑类按钮都加完再加，
        #   这样那些按钮才会出现在它的左侧。
        self._edit_actions: list = []                 # 受总开关控制的动作

        def add_edit_action(act):
            act.setVisible(False)                     # 默认全藏
            self._edit_actions.append(act)
            tb.addAction(act)

        # ★★ v2.7.16：「✳ 添加模式」删除 —— 它跟「➕ 新建站点」是同一件事的
        #   两个入口（老 `_on_add_station_toolbar` 干的事就是把它 setChecked(True)）。
        #   现在「新建站点」自己就是**可勾选开关**：勾上 = 进入添加模式（在地图上
        #   点空白处落站），取消 = 退出。状态一眼看得见，不用再靠底部提示文字。
        #   快捷键 Ctrl+N 保留；老的 Ctrl+M 也继续管用（避免旧习惯失效）。
        self.act_new_station = QAction("➕ 新建站点", self)
        self.act_new_station.setCheckable(True)
        self.act_new_station.setShortcuts(
            [QKeySequence("Ctrl+N"), QKeySequence("Ctrl+M")])
        self.act_new_station.setToolTip(
            "勾选后进入添加模式：在地图空白处点一下即可新建站点")
        self.act_new_station.toggled.connect(self._on_toggle_add_mode)
        add_edit_action(self.act_new_station)

        # ★ v2.6.77：「适配窗口」「100%」按钮删除（用户：上方不要这些）。
        #   快捷键 Ctrl+0 / Ctrl+1 保留 —— 挂在窗口上、不上工具栏。
        act_fit = QAction("适配窗口", self)
        act_fit.setShortcut(QKeySequence("Ctrl+0"))
        act_fit.triggered.connect(self.map_view.fit_map)
        self.addAction(act_fit)

        act_100 = QAction("100% 缩放", self)
        act_100.setShortcut(QKeySequence("Ctrl+1"))
        act_100.triggered.connect(self.map_view.reset_zoom)
        self.addAction(act_100)

        # ★ v2.7.3：新增「删除站点」—— 删右侧面板当前正显示的那个站
        act_del = QAction("🗑 删除站点", self)
        act_del.setToolTip("删除右侧面板当前显示的站点（会先问一句）")
        act_del.triggered.connect(self._on_delete_current_station)
        add_edit_action(act_del)

        # ★ v2.7.2：文字由「保存 (Ctrl+S)」改为「保存」（用户要求），
        #   快捷键 Ctrl+S 照旧绑着，只是不写在按钮上了。
        act_save = QAction("💾 保存", self)
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save.triggered.connect(self._on_save_all)
        add_edit_action(act_save)

        act_undo = QAction("↶ 撤销", self)
        act_undo.setShortcut(QKeySequence.Undo)
        act_undo.triggered.connect(self._on_undo)
        add_edit_action(act_undo)

        act_redo = QAction("↷ 重做", self)
        act_redo.setShortcut(QKeySequence.Redo)
        act_redo.triggered.connect(self._on_redo)
        add_edit_action(act_redo)

        self.act_snap = QAction("🧲 吸附到原图", self)
        self.act_snap.setCheckable(True)
        self.act_snap.setChecked(True)
        self.act_snap.setToolTip(
            "拖动站点时，离官方原图走廊很近（≤30px）就自动吸上去（Ctrl+Z 可撤）")
        self.act_snap.triggered.connect(self._on_toggle_snap)
        add_edit_action(self.act_snap)

        self.act_dev = QAction("📏 偏差检查", self)
        self.act_dev.triggered.connect(self._on_deviation)
        add_edit_action(self.act_dev)

        # ★★ v2.7.14：编辑类按钮加完了 ⇒ 现在才排「模式按钮 + ⚙️」，
        #   于是它们俩永远在最右，编辑按钮永远在模式按钮的**左侧**弹出。
        tb.addAction(self.act_edit_mode)
        self.act_img_settings = QAction("⚙️", self)
        self.act_img_settings.setToolTip("看图模式设置（生成时机 / 定时保存 / 退出询问 / 存哪）")
        self.act_img_settings.triggered.connect(self._open_image_settings)
        tb.addAction(self.act_img_settings)

        # ★★ v2.7.3：这三个**不再占工具栏位置**，改挂 Ctrl+Shift 快捷键。
        #   挂在窗口上（self.addAction）⇒ 按钮看不见，快捷键照样能用，功能一件没丢。
        #   · 自动描线：全图重描会**覆盖手工修好的数据**，不该放在手边误点。
        #   · 批量导入 / 导出：一次性数据迁移才用得着。
        self.act_trace = QAction("🧭 自动描线", self)
        self.act_trace.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self.act_trace.triggered.connect(self._on_auto_trace)
        self.act_trace.setVisible(False)          # 编辑模式开着也不显示（不占位置）
        self.addAction(self.act_trace)

        act_import = QAction("📥 批量导入", self)
        act_import.setShortcut(QKeySequence("Ctrl+Shift+I"))
        act_import.triggered.connect(self._on_import)
        act_import.setVisible(False)
        self.addAction(act_import)

        act_export = QAction("📤 导出当前数据", self)
        act_export.setShortcut(QKeySequence("Ctrl+Shift+E"))
        act_export.triggered.connect(self._on_export)
        act_export.setVisible(False)
        self.addAction(act_export)

        # ★ v2.6.77：「❓ 关于」「⛶ 全屏 (F11)」按钮删除（用户要求）。
        #   F11/Esc 全屏功能保留（_build_fullscreen 的窗口级快捷键仍在）；
        #   关于对话框 _on_about 方法保留（信息面板里可能还有入口）。

        # ★ v2.6.91 + v2.7.2：详情面板「收起/展开」按钮 —— 工具栏**最右**。
        #   图标 = 软件自己的 logo（assets/logo.png，用户选定）。
        self.btn_info_toggle = QPushButton()
        self.btn_info_toggle.setFixedSize(34, 26)
        self.btn_info_toggle.setIcon(_logo_icon(22))
        self.btn_info_toggle.setIconSize(QSize(22, 22))
        self.btn_info_toggle.setToolTip("隐藏站点详情面板")
        self.btn_info_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_info_toggle.clicked.connect(self._on_toggle_info_panel)
        tb.addWidget(self.btn_info_toggle)

    def _on_toggle_edit_mode(self, checked: bool) -> None:
        """★ v2.7.14：模式总开关 —— True=编辑（矢量）/ False=看图（位图）。

        编辑类按钮照旧挂在总开关下，但现在排在**这个按钮的左侧**；
        按钮自己的文字变成"目标模式"，位置一动不动。

        ★ v2.7.33：面板"只读"必须**跟着实际画面**走。
          以前是先 `set_view_mode(not checked)` 把站名锁成只读、再去出图，
          于是"出图失败、画面其实还是矢量"的时候站名已经改不动了（状态与画面对不上）。
          现在改成先尝试出图，成功了才锁面板。
        """
        for a in self._edit_actions:
            a.setVisible(bool(checked))
        want_view = not checked
        ok = True
        if checked:
            self._exit_view_mode()
        else:
            if self.act_new_station.isChecked():
                self.act_new_station.setChecked(False)   # 退出编辑模式顺手关掉添加模式
            if self._img_settings().get("auto_on_enter", True):
                ok = bool(self._enter_view_mode())
                if not ok:
                    self._exit_view_mode()               # 出图失败 ⇒ 明确回到矢量
            else:
                self._exit_view_mode()
        try:
            self.info_panel.set_view_mode(want_view and ok)   # 只在真进了看图时才锁
        except Exception as e:
            print("[view_mode] 面板只读切换失败：", repr(e))
        if checked:
            self.act_edit_mode.setText("🖼 看图模式")
            self._toast("编辑模式（可改站点 / 线路 / 站名）")
        else:
            self.act_edit_mode.setText("✎ 编辑模式")
            self._toast("看图模式（整图变照片，只能改详细信息里的文字）" if ok
                        else "看图模式：出图失败，仍是矢量显示")

    # ------------------------------------------------------------------
    # ★ v2.7.14 看图模式：烘图 / 缓存 / 定时 / 设置
    # ------------------------------------------------------------------
    def _data_dir(self) -> str:
        dm = getattr(self, "dm", None)
        d = getattr(dm, "DATA_DIR", None) or getattr(dm, "data_dir", None)
        if d:
            return str(d)
        from core.data_manager import DATA_DIR
        return str(DATA_DIR)

    def _img_settings(self) -> dict:
        from ui.image_mode import load_settings
        return load_settings(self._data_dir())

    # ★ v2.7.32：图上那份数据 vs 现在这份数据，是否一致
    def _img_sig_now(self) -> str:
        from ui import image_mode as IM
        try:
            return IM.signature(self._data_dir())
        except Exception as e:
            print("[image_mode] 取数据指纹失败：", repr(e))
            return ""

    def _img_is_fresh(self) -> bool:
        """当前 png 是否已经是最新的（数据没变 且 图还在）。

        ★ 用途：退出时的"要不要把整张图保存为图片？"只在**图已经过期**时才弹。
          以前是无条件弹 —— 用户开一下软件、什么元素都没动、关掉也被问一次（实测反馈）。
        """
        done = getattr(self, "_img_sig_done", None)
        if not done:
            return False                      # 本次没烘过图 ⇒ 老老实实问
        if done != self._img_sig_now():
            return False                      # 元素改过了 ⇒ 图过期，要问
        try:
            from ui.image_mode import png_path
            return os.path.exists(png_path(self._data_dir(), self._img_settings()))
        except Exception:
            return False                      # 图被删了 / 路径取不到 ⇒ 还是要问

    def _rebuild_view_image(self, save_png: bool = True, use_cache: bool = True):
        """烘（或读缓存）整张图。返回 QImage；失败返回 None。

        ★ 缓存的意义：烘一次要几秒，数据没变就别让用户每次开软件都等。
        """
        from PySide6.QtCore import QRectF
        from PySide6.QtWidgets import QApplication
        from ui import image_mode as IM

        d = self._data_dir()
        sig = IM.signature(d)
        img, rect = None, None
        if use_cache:
            got = IM.load_cache(d, sig, IM.PX_PER_UNIT)
            if got is not None:
                img, rr = got
                rect = QRectF(*rr)
        if img is None:
            self._toast("正在生成看图…")
            QApplication.processEvents()
            # ★ v2.7.17：烘图 + 存 png 实测要 3 秒左右，主线程这段时间不转
            #   事件循环 ⇒ 心跳停 ⇒ 看门狗会误报「界面卡住」。这里提前打招呼。
            try:
                from core import watchdog
                watchdog.hold(15.0, "烘整张大图并存 png")
            except Exception:
                pass
            import time as _t
            t0 = _t.time()
            img, rect = IM.render_view_image(self.map_view, IM.PX_PER_UNIT)
            if img is None:
                print("[image_mode] 烘图失败：拿不到内容范围")
                self._toast("生成看图失败")
                return None
            IM.save_cache(d, sig, IM.PX_PER_UNIT, img, rect)
            print(f"[image_mode] 烘图 {img.width()}×{img.height()}，"
                  f"耗时 {_t.time() - t0:.1f}s")
        self._view_img = img
        self._view_rect = rect
        # ★ v2.7.32：记下"这张图对应的是哪一份数据"。
        #   退出时拿它和当前数据指纹比 —— 一样就说明元素一个字没改，不必再问要不要存图。
        self._img_sig_done = sig
        if save_png:
            IM.save_png(img, IM.png_path(d, self._img_settings()))
        return img

    def _enter_view_mode(self, force_rebuild: bool = False) -> bool:
        """切到看图模式：把烘好的位图铺到地图上。

        ★ v2.7.33：**手头这张位图是否已经过期，要判一下**。
          以前只看 `img is None or rect is None` ⇒ 在编辑模式里改完站点/线路、
          再切回看图，铺的还是上一张旧图（跟 ⚙️ 里那句"切到看图模式时自动生成图片"
          直接打架）；而 `force_rebuild` 这个参数全项目没有一个调用方传 True，
          等于死代码。现在：数据指纹变了就直接当 force_rebuild 处理。
        """
        img = getattr(self, "_view_img", None)
        rect = getattr(self, "_view_rect", None)
        if not force_rebuild and img is not None and rect is not None:
            # 编辑框里没点保存的字先落盘 —— 不落盘的话指纹读到的还是旧文件，会假命中
            try:
                ip = getattr(self, "info_panel", None)
                if ip is not None and hasattr(ip, "flush_pending"):
                    ip.flush_pending()
                self.dm.save()
            except Exception as e:
                print("[view_mode] 进看图前落盘失败：", repr(e))
            if not self._img_is_fresh():
                print("[view_mode] 数据已变（图过期）→ 重新烘图")
                force_rebuild = True
        if force_rebuild or img is None or rect is None:
            img = self._rebuild_view_image(save_png=True,
                                           use_cache=not force_rebuild)
            # ★★ 必须**重新取** rect：烘图前它是 None，烘完才写进 self._view_rect。
            #    漏了这一行 ⇒ 首次（无缓存）进看图模式永远返回 False ——
            #    图烘出来了、png 也存了，画面却没切（用户报「看图模式失败」）。
            #    缓存命中时 load_cache 顺手给 rect 赋了值，所以只有第一次会犯。
            rect = getattr(self, "_view_rect", None)
        if img is None or rect is None:
            return False
        self.map_view.enter_view_mode(img, rect)
        self.map_view.fit_map()
        return True

    def _exit_view_mode(self) -> None:
        if getattr(self.map_view, "_view_mode", False):
            self.map_view.exit_view_mode()

    def _apply_image_timer(self) -> None:
        """按设置起/停"每 N 分钟自动重新生成并保存"的定时器。"""
        from PySide6.QtCore import QTimer
        mins = int(self._img_settings().get("interval_min", 0) or 0)
        t = getattr(self, "_img_timer", None)
        if t is None:
            t = QTimer(self)
            t.timeout.connect(self._on_image_timer)
            self._img_timer = t
        t.stop()
        if mins > 0:
            t.setInterval(mins * 60 * 1000)
            t.start()

    def _on_image_timer(self) -> None:
        img = self._rebuild_view_image(save_png=True, use_cache=False)
        if img is None:
            return
        if getattr(self.map_view, "_view_mode", False):
            self.map_view.enter_view_mode(img, self._view_rect)
        self._toast("已按定时重新生成并保存图片")

    def _open_image_settings(self) -> None:
        from ui.image_mode import save_settings
        from ui.image_settings_dialog import ImageSettingsDialog
        sec = self._img_settings()
        # ★ v2.7.28：把"本机真正能到的宽度上限"交给弹窗 ⇒ 数字框里压根输不进
        #   无效数字（以前框能填到 780，落地却被 _overlay_width_cap() 静默夹到
        #   屏宽×55%，用户看到的就是"输入了没反应"）。
        dlg = ImageSettingsDialog(self, sec, self._data_dir(),
                                  info_w_max=self._overlay_width_cap())
        # ★ v2.7.19：改完面板宽度仍实时生效（v2.7.28 起为"回车/失焦"触发）
        dlg.info_w_changed.connect(self._on_info_w_live)
        dlg.pan_pad_changed.connect(self._on_pan_pad_live)
        self._settings_dlg = dlg          # ★ 供实际宽度回写（见 _layout_overlays）
        try:
            ok = dlg.exec()
        finally:
            self._settings_dlg = None
        if not ok:
            return
        new = dlg.result_settings()
        save_settings(self._data_dir(), new)
        self._apply_info_w_from_settings()   # ★ v2.7.18：面板宽度改了立刻生效
        self._apply_image_timer()
        if dlg.want_rebuild():
            img = self._rebuild_view_image(save_png=True, use_cache=False)
            if img is not None and getattr(self.map_view, "_view_mode", False):
                self.map_view.enter_view_mode(img, self._view_rect)
            self._toast("已重新生成并保存图片" if img is not None else "重新生成失败")

    def _maybe_auto_start_view_mode(self) -> None:
        """★ 启动后进看图模式（设置里可关）。

        ★ 用单次定时器延后执行：先把窗口画出来，再去烘那张几秒的大图，
          不然开软件会"白等"一段。
        """
        from PySide6.QtCore import QTimer
        # ★ v2.7.17：回归脚本用这个环境变量屏蔽\"开软件直接看图\"，
        #   否则老脚本（按矢量模式写的）一开就全挂。
        if os.environ.get("METROEDITOR_NO_VIEW_START") == "1":
            return
        if not self._img_settings().get("auto_on_start", True):
            return
        QTimer.singleShot(400, self._auto_start_view_mode)

    def _auto_start_view_mode(self) -> None:
        if getattr(self.map_view, "_view_mode", False):
            return
        try:
            self._enter_view_mode()
        except Exception as e:
            print("[view_mode] 启动自动进看图模式失败：", repr(e))

    # ------------------------------------------------------------------
    # ★ v2.6.89：三个新开关 —— 🔒 锁定 / 图例显隐 / 详情面板收起
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # ★ v2.7.0：🔒 双锁 —— 轨迹锁 / 文字锁（右键可单独勾选）
    # ------------------------------------------------------------------
    def _lock_states(self):
        """当前两把锁的状态 (轨迹锁, 文字锁)。"""
        mv = self.map_view
        return (bool(getattr(mv, "stations_locked", False)),
                bool(getattr(mv, "labels_locked", False)))

    def _apply_lock_states(self, body: bool, label: bool, toast: str = "") -> None:
        """落地两把锁：改 MapView 状态 + 刷新图标（上下分色）+ tooltip。"""
        self.map_view.set_drag_locks(body, label)
        try:
            self.btn_lock.set_lock_states(body, label)
        except Exception as e:
            print("[lock] 锁按钮刷新失败：", repr(e))
        self.btn_lock.setToolTip(
            ("🔒 轨迹已锁" if body else "🔓 轨迹可拖")
            + " · " + ("🔒 文字已锁" if label else "🔓 文字可拖")
            + "\n左键：一键全锁/全解　右键：单独勾选")
        if toast:
            self._toast(toast)

    def _on_lock_click(self) -> None:
        """左键：不是「全锁」就全锁，已是「全锁」则全解（用户选定的一键语义）。"""
        body, label = self._lock_states()
        if body and label:
            self._apply_lock_states(False, False, "🔓 已解锁：站点与文字都可拖动")
        else:
            self._apply_lock_states(True, True, "🔒 已全锁：站点与文字都不可拖动")

    def _on_lock_menu(self, pos) -> None:
        """右键：菜单里单独勾选「锁定轨迹」「锁定文字」。"""
        body, label = self._lock_states()
        m = QMenu(self)
        a_body = m.addAction("锁定轨迹")
        a_body.setCheckable(True)
        a_body.setChecked(body)
        a_label = m.addAction("锁定文字")
        a_label.setCheckable(True)
        a_label.setChecked(label)
        act = m.exec(self.btn_lock.mapToGlobal(QPoint(pos)))
        if act is None:
            return                          # 点空白关掉菜单 ⇒ 不改状态
        nb, nl = a_body.isChecked(), a_label.isChecked()
        if (nb, nl) == (body, label):
            return
        msg = []
        if nb != body:
            msg.append("锁定轨迹" if nb else "解锁轨迹")
        if nl != label:
            msg.append("锁定文字" if nl else "解锁文字")
        self._apply_lock_states(nb, nl, "、".join(msg) if msg else "")

    # ------------------------------------------------------------------
    # ★ v2.7.1：地图右键菜单（普通状态下） / 主工具栏显隐
    # ------------------------------------------------------------------
    def _build_search_box(self) -> None:
        """★ v2.7.1：把搜索框挂到**左侧线路图例顶部**（1 号线上方）。"""
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 2, 0, 6)
        lay.setSpacing(4)
        lbl = QLabel("🔍")
        lbl.setStyleSheet("font-size:13px;")
        lay.addWidget(lbl)
        lay.addWidget(self.search_box, 1)
        self.legend_panel.add_persistent_top(row)

    def _set_toolbar_visible(self, on: bool) -> None:
        """主工具栏 显示/隐藏（地图右键菜单 + F11 全屏共用）。"""
        tb = getattr(self, "toolbar", None)
        if tb is None:
            return
        tb.setVisible(bool(on))

    def _build_map_context_menu(self):
        """★ v2.7.1：地图**空白处**右键的菜单（用户指定的顺序）：

            ① 显示/隐藏 上方主工具栏
            ② 显示/隐藏 左侧线路图例
            ③ 显示/隐藏 站点详情面板（右侧）
            ④ 锁定 🔒 → 二级菜单「锁定轨迹」「锁定文字」

        ★ 只在**普通状态**（编辑模式关闭）下建：编辑模式下地图右键另有用途，
          不抢它的菜单（用户原话「在普通状态下(即非编辑状态下)」）。
        ★ 单独抽出来是为了回归能**不弹窗**就验证菜单顺序（探针直接查 actions）。

        返回 (menu, handlers)；编辑模式下返回 (None, None)。
        """
        if self.act_edit_mode.isChecked():
            return None, None
        body, label = self._lock_states()
        m = QMenu(self)

        # ① 主工具栏
        tb_on = self.toolbar.isVisible() if getattr(self, "toolbar", None) else True
        act_tb = m.addAction("隐藏上方主工具栏" if tb_on else "显示上方主工具栏")

        # ② 左侧线路图例
        lg_on = self.legend_panel.isVisible()
        act_lg = m.addAction("隐藏左侧线路图例" if lg_on else "显示左侧线路图例")

        # ③ 右侧站点详情面板
        ip_on = self.info_panel.isVisible()
        act_ip = m.addAction("隐藏站点详情面板" if ip_on else "显示站点详情面板")

        # ④ 锁定（二级菜单）
        sub = m.addMenu("🔒 锁定")
        a_body = sub.addAction("锁定轨迹")
        a_body.setCheckable(True)
        a_body.setChecked(body)
        a_label = sub.addAction("锁定文字")
        a_label.setCheckable(True)
        a_label.setChecked(label)

        handlers = {
            act_tb: lambda: self._set_toolbar_visible(not tb_on),
            act_lg: lambda: self.btn_legend_toggle.setChecked(not lg_on),
            act_ip: lambda: self._on_toggle_info_panel(),
            a_body: lambda: self._apply_lock_states(
                not body, label, "锁定轨迹" if not body else "解锁轨迹"),
            a_label: lambda: self._apply_lock_states(
                body, not label, "锁定文字" if not label else "解锁文字"),
        }
        return m, handlers

    def _on_map_context_menu(self, gpos) -> None:
        m, handlers = self._build_map_context_menu()
        if m is None:
            return
        act = m.exec(gpos)
        if act is None:
            return
        fn = handlers.get(act)
        if fn is not None:
            fn()
        m.deleteLater()

    def _on_toggle_legend(self, on: bool) -> None:
        """左侧线路图例 显示/隐藏（浮层：不再影响地图宽度）。"""
        if on:
            self.legend_panel.show()
        else:
            self._legend_w = self.legend_panel.width() or self._legend_w
            self.legend_panel.hide()
        self._layout_overlays()

    def _on_toggle_info_panel(self) -> None:
        """右侧详情面板 收起（**整条消失**）/ 展开（浮层：不再挤地图）。"""
        if self.info_panel.isVisible():
            self._info_w = self.info_wrap.width() or self._info_w
            self.info_panel.hide()
            self.info_wrap.hide()
            self.btn_info_toggle.setToolTip("显示站点详情面板")
        else:
            self.info_wrap.show()          # ★ 顺序要紧：先放容器，再放面板
            self.info_panel.show()
            self.btn_info_toggle.setToolTip("隐藏站点详情面板")
        # ★ v2.7.2：收起/展开都显示同一个 logo，用 tooltip 说明当前点一下会怎样
        self._layout_overlays()

    # ------------------------------------------------------------------
    # ★ v2.7.13：左右面板 = 地图之上的**浮层**（不再参与布局，不挤地图）
    # ------------------------------------------------------------------
    def _build_overlay_grips(self) -> None:
        """两个浮层靠地图那一侧各挂一条把手，拖动改宽度（替代 splitter）。

        ★ v2.7.16：parent 改成 **map_area**（浮层的同级）。挂在浮层里会被
          浮层自己的内容盖住 ⇒ 光标贴到边缘也不出现拉伸箭头。
        """
        host = getattr(self, "map_area", None) or self
        self.legend_grip = _OverlayGrip(host, "right", self._set_legend_w,
                                        LEGEND_MIN_W,
                                        get_w=lambda: self.legend_panel.width())
        self.info_grip = _OverlayGrip(host, "left", self._set_info_w,
                                      INFO_PANEL_MIN_W,
                                      get_w=lambda: self.info_wrap.width())
        # 浮层没显示时把手也不该出来（否则地图左/右边缘会凭空多一条热区）
        self.legend_grip.hide()
        self.info_grip.hide()

    def _set_legend_w(self, w: int) -> None:
        self._legend_w = int(w)
        self._layout_overlays()

    def _set_info_w(self, w: int) -> None:
        self._info_w = int(w)
        self._layout_overlays()
        # ★ v2.7.18：拖出来的宽度**记住**（防抖 600ms 后写盘，拖动过程不狂写）
        self._save_info_w_debounced()

    # ---- v2.7.18：右侧面板宽度的读 / 写 ----
    def _info_w_clamp(self, w: int) -> int:
        """★ v2.7.28：把宽度夹到"本机真能落地"的范围（360 ~ 屏宽55% 与 780 取小）。"""
        return max(INFO_PANEL_MIN_W, min(self._overlay_width_cap(), int(w)))

    def _saved_info_w(self) -> int:
        """设置里的面板宽度（缺/坏值 ⇒ 520，再按 360~本机上限 夹一下）。"""
        try:
            from ui.image_mode import load_settings
            w = int(load_settings(self._data_dir()).get("info_panel_w", 520) or 520)
        except Exception:
            w = 520
        return self._info_w_clamp(w)

    def _save_info_w_debounced(self) -> None:
        t = getattr(self, "_info_w_timer", None)
        if t is None:
            from PySide6.QtCore import QTimer
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(self._save_info_w)
            self._info_w_timer = t
        t.start(600)

    def _save_info_w(self) -> None:
        """把当前面板宽度写回 view_settings.json（下次启动沿用）。"""
        try:
            from ui.image_mode import load_settings, save_settings
            sec = load_settings(self._data_dir())
            if int(sec.get("info_panel_w", 0) or 0) == int(self._info_w):
                return
            sec["info_panel_w"] = int(self._info_w)
            save_settings(self._data_dir(), sec)
        except Exception as e:
            print("[ui] 保存面板宽度失败：", repr(e))

    def _on_info_w_live(self, w: int) -> None:
        """★ v2.7.19：⚙️ 里改数字 ⇒ 立刻改面板宽度并写进设置（不必点确定）。"""
        self._info_w = self._info_w_clamp(w)
        self._layout_overlays()
        t = getattr(self, "_info_w_timer", None)
        if t is not None:
            t.stop()                # 别让防抖定时器随后再写一遍
        self._save_info_w()

    # ---- v2.7.20：拖动留白（"元素与屏幕边还留多少空白"）----
    def _saved_pan_pad(self) -> int:
        # ★★ v2.7.30：原来的 min(400, v) 是**第二个夹取点** —— 即使 ⚙️ 里把上限
        #   抬到 2000，这里还会把大值夹回 400，重启后照样失效。
        #   现在与弹窗共用同一个常量 PAN_PAD_MAX。
        try:
            from ui.image_mode import load_settings
            from ui.image_settings_dialog import PAN_PAD_MAX, PAN_PAD_MIN
            v = int(load_settings(self._data_dir()).get("pan_pad_scene", 24) or 0)
        except Exception:
            v = 24
        return max(PAN_PAD_MIN, min(PAN_PAD_MAX, v))

    def _apply_pan_pad_from_settings(self) -> None:
        try:
            self.map_view.set_pan_pad(self._saved_pan_pad())
        except Exception as e:
            print("[ui] 应用拖动留白失败：", repr(e))

    def _on_pan_pad_live(self, v: int) -> None:
        """★ v2.7.20：⚙️ 里改拖动留白 ⇒ 立刻生效 + 写进设置。"""
        try:
            self.map_view.set_pan_pad(v)
        except Exception as e:
            print("[ui] 设拖动留白失败：", repr(e))
        try:
            from ui.image_mode import load_settings, save_settings
            sec = load_settings(self._data_dir())
            if int(sec.get("pan_pad_scene", -1) or -1) != int(v):
                sec["pan_pad_scene"] = int(v)
                save_settings(self._data_dir(), sec)
        except Exception as e:
            print("[ui] 保存拖动留白失败：", repr(e))

    def _apply_info_w_from_settings(self) -> None:
        """⚙️ 里改了数字 ⇒ 立刻把面板调到新宽度。"""
        w = self._saved_info_w()
        if w != self._info_w:
            self._info_w = w
        self._layout_overlays()

    def _overlay_width_cap(self) -> int:
        """单个浮层的宽度上限：屏宽 55% 与 780 取小（v2.7.12 定的手感）。"""
        scr = QGuiApplication.primaryScreen()
        aw = scr.availableGeometry().width() if scr is not None else 1920
        return max(360, min(INFO_PANEL_MAX_W, int(aw * 0.55)))

    def _layout_overlays(self) -> None:
        """按「记忆宽度 + 限幅」把两个浮层摆到地图上（地图本身尺寸不动）。

        ★ 地图视口宽度**恒定** —— 面板出现/消失、拖宽/拖窄都不再改变地图，
          这正是用户要的"覆盖下方的图，而不是把图往中间挤"。
        ★ 两个浮层同时开着时，若合计宽到快把地图盖满，等比收缩，至少给地图
          留 MAP_MIN_VISIBLE（320px）露出来。

        ★★ v2.7.33：注意这里**收缩不动 Qt 的硬下限** —— 图例控件自己的
          minimumWidth 是 196、详情面板是 480，`setGeometry` 传进去的宽度会被
          Qt 顶回这两个值。所以"至少留 320px"这条**最终**是靠窗口的最小宽度
          （= 196 + 480 + 320 = 996）兜住的，见 `__init__` 里那句
          `setMinimumWidth`。这里只负责"窗口够宽时，别把地图挤太狠"。
        """
        area = getattr(self, "map_area", None)
        if area is None:
            return
        W, H = area.width(), area.height()
        if W <= 0 or H <= 0:
            return
        lw = self._legend_w if self.legend_panel.isVisible() else 0
        iw = self._info_w if self.info_panel.isVisible() else 0
        cap = self._overlay_width_cap()
        # 两侧都在时：合计不许吃掉整块地图
        if lw > 0 and iw > 0 and lw + iw > max(W - MAP_MIN_VISIBLE, 0):
            k = max(W - MAP_MIN_VISIBLE, 1) / float(lw + iw)
            lw, iw = int(lw * k), int(iw * k)
        if lw > 0:
            lw = min(max(lw, LEGEND_MIN_W), min(cap, max(W - MAP_MIN_VISIBLE, LEGEND_MIN_W)))
            self.legend_panel.setGeometry(0, 0, lw, H)
            self.legend_panel.raise_()
            g = getattr(self, "legend_grip", None)
            if g is not None:
                # ★ v2.7.16：坐标现在是 **map_area 坐标**（把手已改挂 map_area），
                #   位置 = 浮层靠地图那一侧的边缘（贴内侧 GRIP_W px）。
                g.setGeometry(lw - g.width(), 0, g.width(), H)
                g.show()
                g.raise_()          # ★ 压在浮层之上，热区才抢得到鼠标
        else:
            g = getattr(self, "legend_grip", None)
            if g is not None:
                g.hide()
        if iw > 0:
            iw = min(max(iw, INFO_PANEL_MIN_W), min(cap, max(W - MAP_MIN_VISIBLE, INFO_PANEL_MIN_W)))
            self.info_wrap.setGeometry(W - iw, 0, iw, H)
            self.info_wrap.raise_()
            # ★ v2.7.28：记住**真正落地**的宽度（可能被 cap 或"给地图留
            #   320px"压过）⇒ 回写进 ⚙️ 的数字框，不让它显示假值。
            self._info_w_actual = int(iw)
            g = getattr(self, "info_grip", None)
            if g is not None:
                g.setGeometry(W - iw, 0, g.width(), H)
                g.show()
                g.raise_()
        else:
            g = getattr(self, "info_grip", None)
            if g is not None:
                g.hide()
        self._push_applied_info_w()
        # ★ v2.7.16：把"左右各被浮层遮住多少 px"告诉地图 —— 居中 / 适配窗口
        #   一律按**可见区**算，定位过去的站点不会压在面板底下。
        try:
            self.map_view.set_view_insets(lw, iw)
        except Exception as e:
            print("[overlay] set_view_insets 失败：", repr(e))

    def _push_applied_info_w(self) -> None:
        """⚙️ 开着时，把真正落地的面板宽度回写进那个数字框（v2.7.28）。"""
        dlg = getattr(self, "_settings_dlg", None)
        actual = getattr(self, "_info_w_actual", None)
        if dlg is None or actual is None:
            return
        try:
            if dlg.isVisible():
                dlg.show_applied_w(int(actual))
        except Exception as e:
            print("[ui] 回写面板宽度失败：", repr(e))

    def _build_fullscreen(self):
        """F11 全屏：进入/退出互相切换；Esc 退出全屏。

        ★ 全屏时不改变缩放级别，只让地图区域变大；退出后恢复原窗口几何。
        """
        self._was_maximized = False
        self._fs_action = QAction("⛶ 全屏 (F11)", self)
        self._fs_action.setShortcut(QKeySequence("F11"))
        self._fs_action.setCheckable(True)
        self._fs_action.triggered.connect(self.toggle_fullscreen)
        self.addAction(self._fs_action)          # 无工具栏也能用

        self._esc_action = QAction("退出全屏", self)
        self._esc_action.setShortcut(QKeySequence("Esc"))
        self._esc_action.triggered.connect(self._on_esc_pressed)
        self.addAction(self._esc_action)

    def _on_esc_pressed(self) -> None:
        """Esc：先关搜索候选面板；再解除固定气泡；都没有才退出全屏。"""
        if getattr(self, "search_popup", None) is not None and self.search_popup.isVisible():
            self.search_popup.hide()
            return
        if self.tip.pinned:
            self.tip.unpin()                  # ★ v2.6.79：Esc 先解除固定气泡
            return
        self.set_fullscreen(False)

    def toggle_fullscreen(self):
        self.set_fullscreen(not self.isFullScreen())

    def set_fullscreen(self, on: bool) -> None:
        on = bool(on)
        if on == self.isFullScreen():
            self._fs_action.setChecked(on)
            return
        if on:
            self._was_maximized = self.isMaximized()
            self._pre_fs_geom = self.geometry()
            # 先中止缩放动画/快照：视口尺寸马上要变，快照会失效
            self.map_view._abort_zoom_snap()
            self.showFullScreen()
        else:
            self.showNormal()
            if getattr(self, "_was_maximized", False):
                self.showMaximized()
        self._fs_action.setChecked(self.isFullScreen())
        # ★ v2.7.1：F11 进入全屏 ⇒ **默认不显示上方主工具栏**（用户要求）；
        #   退出全屏再恢复显示。（要在地图右键菜单里手动开关也行 —— 那边的
        #   "显示/隐藏 主工具栏"与这里共用同一个 _set_toolbar_visible。）
        if self.isFullScreen():
            self._set_toolbar_visible(False)
        else:
            self._set_toolbar_visible(True)
        # 视口尺寸变化后让地图重新按新尺寸渲染
        self.map_view.viewport().update()
        self.lbl_hint.setText(
            "F11 全屏 / Esc 退出 · 按住空白处拖动平移 · 滚轮缩放 · Ctrl+S 保存"
            if self.isFullScreen() else
            "按住空白处拖动可平移地图 · ↑↓←→ 选站 · Enter 编辑 · 滚轮缩放 · Ctrl+S 保存 · F11 全屏"
        )

    def keyPressEvent(self, event):
        # F11 在无工具栏焦点时也能生效（部分情况下快捷键会被子控件吞掉）
        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def _build_statusbar(self):
        """★ v2.6.77：底部状态栏整行删除（用户：软件下方不要占用空间）。

        lbl_* 对象保留（不挂到任何布局、不显示）—— 全代码 7 处
        setText（_refresh_status/_mark_saved/_sync_zoom 等）不用改，
        写到不可见标签上零成本。
        """
        self.lbl_zoom = QLabel("缩放: 100%", self)
        self.lbl_count = QLabel("站点数: 0", self)
        self.lbl_save = QLabel("已保存: --", self)
        # ★ 真实的落盘时刻（原状态栏显示它）。必须在第一次 _refresh_status() 之前
        #   就存在 —— 见 _mark_saved 的说明：以前这里显示的是"当前时间"，是假的。
        self._last_save: str = ""
        self.lbl_hint = QLabel(
            "按住空白处拖动可平移地图 · ↑↓←→ 选站 · Enter 编辑 · 滚轮缩放 · Ctrl+S 保存",
            self,
        )
        self.lbl_hint.hide()
        self.lbl_zoom.hide()
        self.lbl_count.hide()
        self.lbl_save.hide()

    def _toast(self, text: str, color: str = "#22C55E") -> None:
        """屏幕正中弹一行大字（用户：「保存后需要在屏幕中间弹出来绿色文字」）。

        ★ 挂在 map_view 的视口上而不是整个窗口：地图占了大半屏，
          视觉"中间"就是它。★ `WA_TransparentForMouseEvents` 必须开 ——
          否则这块浮层会把鼠标吃掉，正好挡住它下面的站点，点不动。
        """
        vp = self.map_view.viewport()
        if getattr(self, "_toast_lbl", None) is None:
            self._toast_lbl = QLabel(vp)
            self._toast_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            self._toast_lbl.setAlignment(Qt.AlignCenter)
            f = self._toast_lbl.font()
            f.setPixelSize(30)
            f.setBold(True)
            self._toast_lbl.setFont(f)
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._toast_lbl.hide)
        lb = self._toast_lbl
        lb.setText(text)
        lb.setStyleSheet(
            f"color: {color}; background: rgba(255,255,255,216);"
            f"border-radius: 10px; padding: 10px 26px;")
        lb.adjustSize()
        lb.move(max(0, (vp.width() - lb.width()) // 2),
                max(0, (vp.height() - lb.height()) // 2))
        lb.raise_()
        lb.show()
        self._toast_timer.start(1200)

    def _on_toggle_underlay(self, on: bool) -> None:
        """Ctrl+B / 工具栏：开关"官方原图垫底"（对照着手动调站点用）。"""
        shown = self.map_view.toggle_underlay(on)
        self.act_underlay.setChecked(shown)
        self._toast("原图对照：开" if shown else "原图对照：关",
                    "#22C55E" if shown else "#64748B")

    # ------------------------------------------------------------------
    # ★ v2.6.55 自动追踪（甲 描线 / 乙 吸附 / 偏差提示）
    # ------------------------------------------------------------------
    def _on_toggle_snap(self, on: bool) -> None:
        """乙：拖动站点时吸到官方原图走廊上。"""
        try:
            from ui import metro_render as MR
            MR.TRACE_SNAP = bool(on)
        except Exception:
            pass
        self._toast("吸附到原图：开" if on else "吸附到原图：关",
                    "#22C55E" if on else "#64748B")

    def _on_auto_trace(self) -> None:
        """甲：照**官方原图**把线条描出来。"""
        try:
            from ui import trace_assist as TA
        except Exception:
            TA = None
        if TA is None or not TA.available():
            QMessageBox.warning(
                self, "自动描线",
                "找不到走廊数据 `data/trace_cloud.json`。\n\n"
                "它是从官方原图 assets/shenzhen_metro.png 里抽出来的中心线，\n"
                "自动描线全靠它 —— 文件没了，这个功能就没法用。")
            return
        dm = get_data_manager()
        have = dm.lines_doc.get("traced")
        have = len(have) if isinstance(have, dict) else 0
        box = QMessageBox(self)
        box.setWindowTitle("自动描线（按官方原图）")
        box.setText(
            "照官方原图 shenzhen_metro.png 里**真的那条线**，把我们的线路描过去。\n\n"
            f"当前已经描过 {have} 段。\n"
            "★ 整批操作只压**一份**快照 ⇒ 不满意按一下 Ctrl+Z 全撤回来。\n"
            "★ 原图上被别的线/站牌盖住、实在描不出来的段会**保持原样**并列出名单，"
            "绝不瞎猜。")
        b_all = box.addButton("🧭 全图描线", QMessageBox.AcceptRole)
        b_clr = box.addButton("🧹 清除描线", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(b_all)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_all:
            ok, tot, failed = self.map_view.auto_trace_all()
            msg = QMessageBox(self)
            msg.setWindowTitle("自动描线")
            msg.setText("描好了 %d / %d 段（%.0f%%）。\n\n"
                        "不满意就按 Ctrl+Z，一下全撤。"
                        % (ok, tot, 100.0 * ok / max(tot, 1)))
            if failed:
                msg.setDetailedText(
                    "描不出来的 %d 段（保持原来的画法）：\n" % len(failed)
                    + "\n".join("  · " + s for s in failed))
            msg.exec()
        elif clicked is b_clr:
            n = self.map_view.clear_auto_trace()
            self._toast("已清除 %d 段描线" % n if n else "本来就没有描线",
                        "#22C55E" if n else "#64748B")

    def _on_deviation(self) -> None:
        """偏差提示：把"离官方走廊最远"的站列出来（这就是体检报告）。"""
        try:
            from ui import trace_assist as TA
        except Exception:
            TA = None
        if TA is None or not TA.available():
            QMessageBox.warning(self, "偏差检查", "找不到 data/trace_cloud.json。")
            return
        rows = self.map_view.deviation_rows()
        if not rows:
            QMessageBox.information(
                self, "偏差检查",
                "所有站都贴在官方走廊上（偏差 < 25px）✅")
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("偏差检查")
        msg.setText("离官方走廊 ≥25px 的有 %d 处（最多列 60 条）。\n\n"
                    "名单上的站就是需要手动拖一下的 —— 开着「🧲 吸附到原图」"
                    "拖过去会自己啪一下归位。\n"
                    "★ 偏差大也可能是**原图本身那条线就是绕的**，"
                    "那就该用 Ctrl+右键 给这段选「按官方原图描这一段」。"
                    % len(rows))
        msg.setDetailedText("\n".join(
            "  %-10s %-6s号线  偏差 %.0f px" % (n, l, d) for n, l, d in rows))
        msg.exec()

    def _mark_saved(self) -> None:
        """记下**真实的**落盘时刻 —— 状态栏「已保存」显示的就是它。

        ★ 修掉的坑（v2.5.5）：原来 _refresh_status() 里写的是
              self.lbl_save.setText("已保存: " + time.strftime("%H:%M:%S"))
          取的是【当前时间】。而 _refresh_status() 有 7 处调用，其中**启动时**
          就调了一次 —— 于是刚打开软件，状态栏就显示"已保存: 04:41:41"，
          任何一次状态刷新都会把它刷成"现在"，用户会以为数据刚落盘（其实
          一次都没写）。倒查数据异常时，这个时间还会把人带偏（它不能当线索用）。
        """
        self._last_save = time.strftime("%H:%M:%S")
        # ★ v2.6.35：屏幕正中弹绿色"已保存"
        self._toast("已保存")

    # ------------------------------------------------------------------
    # v2.6.34：撤销 / 重做
    # ------------------------------------------------------------------
    def _snapshot(self) -> dict:
        """把"能被改的三类数据"整个拷一份（站点 / 线路 / 线路号偏移）。"""
        return {
            "stations": copy.deepcopy(self.dm.stations_doc),
            "lines": copy.deepcopy(self.dm.lines_doc),
            "badges": copy.deepcopy(load_badge_offsets()),
        }

    def _save_data(self) -> None:
        """写盘 + 记下真实时刻。★ 业务保存一律走这里，别再直接 dm.save()。

        ★ v2.6.34：这里同时是**撤销栈的唯一入栈点** —— 写盘前先把"上次落盘后
          的状态"压进 undo 栈（那正是本次改动**之前**的样子），然后刷新
          `_snap_before`。恢复数据时（_restoring）不压栈，否则撤销自己会
          变成一步可撤销的操作，Ctrl+Z 永远停不下来。
        """
        if not self._restoring and self._snap_before is not None:
            self._undo_stack.append(self._snap_before)
            if len(self._undo_stack) > UNDO_DEPTH:
                self._undo_stack.pop(0)
            self._redo_stack.clear()
        self.dm.save()
        self._mark_saved()
        self._snap_before = self._snapshot()

    def _restore_snapshot(self, snap: dict) -> None:
        """把一份快照灌回数据层并重建画面（顺序照 `_on_import`）。"""
        self._restoring = True
        try:
            self.dm.stations_doc = snap["stations"]
            self.dm.lines_doc = snap["lines"]
            self.dm.stations_doc.setdefault("stations", {})
            self.dm.lines_doc.setdefault("lines", [])
            save_badge_offsets(snap.get("badges") or {})
            self.dm.save()
            self._mark_saved()
            self.map_view.reload_stations(self.dm.all_stations())
            self.map_view.rebuild_lines()
            self.map_view.rebuild_terminal_badges()
            self.legend_panel.set_lines(self.dm.all_lines(), self.dm.all_stations())
            self._refresh_status()
        finally:
            self._restoring = False
        self._snap_before = self._snapshot()

    def _on_undo(self) -> None:
        if not self._undo_stack:
            self.lbl_hint.setText("没有可撤销的操作了")
            return
        self._redo_stack.append(self._snapshot())
        self._restore_snapshot(self._undo_stack.pop())
        self._toast("已撤销", "#0EA5E9")
        self.lbl_hint.setText(
            f"已撤销（还能撤销 {len(self._undo_stack)} 步 / 重做 {len(self._redo_stack)} 步）")

    def _on_redo(self) -> None:
        if not self._redo_stack:
            self.lbl_hint.setText("没有可重做的操作了")
            return
        self._undo_stack.append(self._snapshot())
        self._restore_snapshot(self._redo_stack.pop())
        self._toast("已重做", "#0EA5E9")
        self.lbl_hint.setText(
            f"已重做（还能撤销 {len(self._undo_stack)} 步 / 重做 {len(self._redo_stack)} 步）")

    def _refresh_status(self):
        self.lbl_count.setText(f"站点数: {len(self.dm.all_stations())}")
        self.lbl_save.setText("已保存: " + (self._last_save or "--"))
        self.lbl_zoom.setText(f"缩放: {int(self.map_view._scale * 100)}%")

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _wire_signals(self):
        # 单击 → 选中 → 信息面板
        self.map_view.station_clicked.connect(self._on_station_clicked)
        # ★ v2.6.90：左键单击空白 ⇒ 收起右侧详情面板（中键拖底图不触发）
        self.map_view.map_empty_clicked.connect(self._on_map_empty_clicked)
        # ★ v2.7.1：地图空白处**右键** ⇒ 主工具栏/图例/详情面板/锁定 四类菜单
        self.map_view.blank_context_requested.connect(self._on_map_context_menu)
        # ★ v2.6.91：详情面板 🎯 按钮 ⇒ 跳转到该站（同搜索定位）
        self.info_panel.locate_requested.connect(self._locate_station)
        # 双击 → 弹窗编辑
        self.map_view.station_double_clicked.connect(self._on_station_double_clicked)
        # 拖动 → 更新坐标并落盘
        self.map_view.station_moved.connect(self._on_station_moved)
        # v2.6.32：单独拖动站名 → 把偏移落盘（圆点坐标不动）
        self.map_view.label_moved.connect(self._on_label_moved)
        # 地图空白处双击 → 新建
        self.map_view.add_station_requested.connect(self._on_add_station_at)

        # 信息面板
        self.info_panel.save_requested.connect(self._on_info_save)
        self.info_panel.auto_saved.connect(self._on_info_autosaved)   # v2.6.57
        self.info_panel.edit_in_dialog_requested.connect(self._on_station_double_clicked)
        self.info_panel.delete_requested.connect(self._on_delete_station)

        # 缩放变化 → 状态栏
        self.map_view.zoom_changed.connect(self._on_zoom_changed)

        # 图例
        self.legend_panel.line_hovered.connect(self.map_view.highlight_line)
        self.legend_panel.line_clicked.connect(self._on_legend_clicked)
        self.legend_panel.line_double_clicked.connect(self._on_legend_double_clicked)
        self.map_view.isolation_changed.connect(self._on_isolation_changed)

    def _on_legend_clicked(self, line_id: str) -> None:
        self.map_view.fit_to_line(line_id)
        ln = self.dm.get_line(line_id)
        if ln:
            self.lbl_hint.setText(f"📍 已定位到 {ln['name']}（{ln.get('alias','')}）")

    # ------------------------------------------------------------------
    # 单独显示某条线路（双击图例）
    # ------------------------------------------------------------------
    def _on_legend_double_clicked(self, line_id: str) -> None:
        """双击图例 → 只看这一条；再双击同一条 → 回到全图。"""
        if self.map_view.isolated_line() == line_id:
            self._exit_isolation()
        else:
            self.map_view.set_isolated_line(line_id)

    def _exit_isolation(self) -> None:
        self.map_view.set_isolated_line("")

    def _on_isolation_changed(self, line_id: str) -> None:
        """隔离状态变了：更新卡片、图例选中态、提示条。"""
        self.legend_panel.set_isolated(line_id)

        if not line_id:
            self.consist_card.hide()
            self.isolated_close.hide()
            self.lbl_hint.setText("已恢复显示所有线路")
            return

        ln = self.dm.get_line(line_id)
        if not ln:
            self.consist_card.hide()
            self.isolated_close.hide()
            return

        self.consist_card.set_line(
            ln.get("name", line_id),
            ln.get("color", "#888888"),
            consist_for(line_id),
        )
        # ★ 顺序：先 show() 再摆位置 —— 摆位置用的就是视口尺寸，无所谓，
        #   但必须最后 raise_()，否则缩放动画那层合成快照（它会盖满视口并抬层）
        #   会把卡片蒙在下面。
        self.consist_card.show()
        self._reposition_consist_card()
        # 右上角红色大 ✕ 跟卡片同生共死
        self.isolated_close.show()
        self.isolated_close.raise_()

        n = len(ln.get("stations") or [])
        has = consist_for(line_id)
        tail = "（车厢编组见右下角）" if has else "（这条线路暂无车厢编组资料）"
        self.lbl_hint.setText(
            f"🔍 只看「{ln.get('name', line_id)}」，共 {n} 站 {tail}"
            f"· 点右上角 ✕ / 再双击该行 / 按 Esc 退出")

    def _reposition_consist_card(self) -> None:
        """把车厢编组卡片贴到地图的右下角。

        ★★ 位置**由 MapView 在每次绘制前统一校正**（`_layout_chrome`），
           这里只是"立刻摆一次"，免得显示的第一帧还在旧位置。
           不要自己算坐标自己 move —— 那样读到的是**上一帧**的视口尺寸，
           连续改窗口大小时位置会一帧一帧漂出去（实测右边距能漂到 -284，
           整块跑到视口右边界外）。
        """
        self.map_view._layout_chrome()
        card = getattr(self, "consist_card", None)
        if card is not None:
            card.raise_()

    # ------------------------------------------------------------------
    # 搜索（v2.5.0：边打字边在下面列候选）
    # ------------------------------------------------------------------
    def _line_short_names(self) -> dict:
        """{线路id: 短名}。短名把"号线"去掉（"1号线" → "1"），好塞进候选行右侧。"""
        out = {}
        for ln in self.dm.all_lines():
            lid = ln.get("id")
            name = str(ln.get("name") or lid or "")
            out[lid] = name.replace("号线", "")
        return out

    def _search_candidates(self, text: str, limit: int = 0) -> list:
        """按站名筛选站点，返回排好序的 station_id 列表。

        排序规则（越靠前越"像你要找的"）：
          0 完全一样  →  1 以输入开头  →  2 名字中间包含  →  3 站点id里包含
        同一档里按「名字短的优先」，再按字典序，保证结果稳定不跳动。
        """
        text = (text or "").strip()
        if not text:
            return []
        tl = text.lower()
        tiers = {0: [], 1: [], 2: [], 3: []}
        for sid, data in self.dm.all_stations().items():
            name = str(data.get("station_name") or sid)
            nl = name.lower()
            if tl == nl:
                tier = 0
            elif nl.startswith(tl):
                tier = 1
            elif tl in nl:
                tier = 2
            elif tl in sid.lower():
                tier = 3
            else:
                continue
            tiers[tier].append((len(name), name, sid))
        out = []
        for t in sorted(tiers):
            tiers[t].sort()
            out.extend(sid for _, _, sid in tiers[t])
        return out[:limit] if limit else out

    def _on_search_text_changed(self, text: str) -> None:
        """搜索框里每敲一个字就调一次。"""
        text = (text or "").strip()
        if not text:
            self.search_popup.hide()
            return
        sids = self._search_candidates(text)
        shorts = self._line_short_names()
        rows = []
        for sid in sids[:SUGGEST_MAX_ROWS]:
            data = self.dm.get_station(sid) or {}
            name = str(data.get("station_name") or sid)
            lids = [lid for lid in (data.get("lines") or []) if lid]
            info = " · ".join(shorts.get(lid, str(lid)) for lid in lids[:4])
            rows.append((sid, name, info))
        self.search_popup.set_items(rows, len(sids))
        self.search_popup.show_at(self.search_box)

    def _on_suggest_picked(self, station_id: str) -> None:
        """点了候选 / 或按回车选中高亮项。"""
        self.search_popup.hide()
        data = self.dm.get_station(station_id) or {}
        name = str(data.get("station_name") or station_id)
        # ★ 回填搜索框但不重新触发下拉（否则刚选完立刻又弹一次）
        self.search_box.blockSignals(True)
        self.search_box.setText(name)
        self.search_box.blockSignals(False)
        self._locate_station(station_id, name)

    def _locate_station(self, station_id: str, label: str = "") -> None:
        """选中 + 放大定位 + 右侧面板显示该站。"""
        self.map_view.select_station(station_id)
        self.map_view.zoom_to_station(station_id)
        # ★ v2.6.90：定位到的站点（圆点+站名文字）闪几下，方便在密集图上找到
        self.map_view.blink_station(station_id)
        self.info_panel.show_station(station_id)
        self.lbl_hint.setText(f"🔍 已定位到「{label or station_id}」")
        self.map_view.setFocus()

    def _on_search(self) -> None:
        text = self.search_box.text().strip()
        if not text:
            return
        self.search_popup.hide()
        sids = self._search_candidates(text)
        if sids:
            sid = sids[0]
            data = self.dm.get_station(sid) or {}
            self._locate_station(sid, str(data.get("station_name") or sid))
        else:
            self.lbl_hint.setText(f"⚠ 未找到站点「{text}」")
            self.map_view.setFocus()

    def _handle_search_key(self, event) -> bool:
        """搜索框里的按键：↑↓ 选、Enter 选中、Esc 关面板。返回 True = 已处理。"""
        key = event.key()
        if key == Qt.Key_Escape:
            if self.search_popup.isVisible():
                self.search_popup.hide()
                return True
            return False
        if not self.search_popup.isVisible():
            return False
        if key in (Qt.Key_Down, Qt.Key_Up):
            self.search_popup.move_active(1 if key == Qt.Key_Down else -1)
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            sid = self.search_popup.active_station_id()
            if sid:
                self._on_suggest_picked(sid)
                return True
            return False       # 没高亮 → 放开，走原来的"回车定位第一个"
        return False

    def _on_zoom_changed(self, scale: float) -> None:
        self.lbl_zoom.setText(f"缩放: {int(scale * 100)}%")

    # ------------------------------------------------------------------
    # 事件过滤：鼠标在地图上的悬浮检测
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self.map_view.viewport():
            # 视口尺寸变了 → 右下角卡片要重新贴边（含缩放动画期间快照 label 抬到上层）
            if event.type() == QEvent.Resize:
                self._reposition_consist_card()
            # 鼠标移动/进出时，处理悬浮提示
            if event.type() == QEvent.MouseMove:
                self._handle_hover(event.position().toPoint() if hasattr(event, 'position') else event.pos())
            elif event.type() == QEvent.Leave:
                # ★ v2.6.79：固定气泡时鼠标可能是"移进气泡"，不许藏
                if not self.tip.pinned:
                    self.tip.hide()
            elif event.type() == QEvent.MouseButtonPress:
                # ★ v2.6.79：在地图上按下（空白/别的站）⇒ 解除固定气泡。
                #   若按的还是站点，随后的 click 会重新 pin，视觉上无缝。
                if self.tip.pinned:
                    self.tip.unpin()
            elif event.type() == QEvent.Enter:
                pass
        elif obj is self.search_box and event.type() == QEvent.KeyPress:
            # v2.5.0：候选面板开着时，↑↓EnterEsc 先归候选面板用。
            # 注意面板是独立顶层窗口、键盘焦点一直留在搜索框里，
            # 所以只能在这里"转发"按键，不能靠面板自己接。
            if self._handle_search_key(event):
                return True
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        """★ v2.7.1：首次显示时补做一次浮层定位（见 __init__ 里的注释）。"""
        super().showEvent(event)
        if getattr(self, "_pending_overlay_layout", False):
            self._pending_overlay_layout = False
            self._layout_overlays()
        # ★ v2.7.20：拖动留白（设置里可调）—— 启动就应用一次
        self._apply_pan_pad_from_settings()
        # ★ v2.7.14：启动后自动进一次看图模式（只做一次）
        if not getattr(self, "_view_autostart_done", False):
            self._view_autostart_done = True
            self._apply_image_timer()
            self._maybe_auto_start_view_mode()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # ★ v2.7.13：窗口大小变了（含跨屏 / 换分辨率），浮层几何跟着重摆
        self._layout_overlays()
        # 面板是独立顶层窗口、贴的是屏幕绝对坐标：主窗口一变大小/移动，
        # 它就会孤零零停在原地 —— 直接收起来
        if getattr(self, "search_popup", None) is not None and self.search_popup.isVisible():
            self.search_popup.hide()

    def moveEvent(self, event):
        super().moveEvent(event)
        if getattr(self, "search_popup", None) is not None and self.search_popup.isVisible():
            self.search_popup.hide()

    def _handle_hover(self, view_pos) -> None:
        scene_pos = self.map_view.mapToScene(view_pos)
        # ★ v2.7.18：看图模式 —— 矢量图元全藏着，item 的 hover 事件根本不会来。
        #   这里按命中表反查（圆点 + 站名框），命中就把站点"放大光晕"交给
        #   MapView 补画、气泡照常弹 ⇒ 看图模式和编辑模式的悬浮手感一致。
        if getattr(self.map_view, "_view_mode", False):
            self._handle_hover_view_mode(scene_pos, view_pos)
            return
        # ★ v2.7.8：for_hover=True —— 不吃 hover 的图元（@alt 副站体）不许认领，
        #   否则"光标变手型但气泡不出"，且电车/云巴的字框会抢走地铁站的圆点。
        item = self.map_view.station_at(scene_pos, for_hover=True)
        # ★ v2.6.79：气泡被"固定"时（单击站点后），鼠标可以移进气泡里
        #   拖滚动条看多图 —— 这期间地图上的 hover 逻辑一律不许把它藏掉。
        if self.tip.pinned:
            if item is None:
                return
            sid = item.data.get("station_id") or item.data.get("station_name")
            if sid == self.tip.pinned_station_id:
                return                      # 还在原站点上，什么都不做
            # 悬浮到别的站点 ⇒ 固定自然解除，继续走下面的正常悬浮
        if item is None:
            self.tip.hide()
            return
        # ★ v2.6.75：光标压在**图标标签**上时只显示图标 tooltip（hoverMoveEvent
        #   里 QToolTip.showText），不连带弹站点介绍气泡 —— 用户明确要求。
        item_pt = item.mapFromScene(scene_pos)
        if item._tag_text_at(item_pt):
            self.tip.hide()
            return
        # 显示 tooltip（有图片的话带上第一张；多图时提示"单击站点查看全部"）
        global_pos = self.map_view.viewport().mapToGlobal(view_pos)
        self.tip.show_for(global_pos, item.data, self.dm.resolve_images(item.data))

    def _handle_hover_view_mode(self, scene_pos, view_pos) -> None:
        """★ v2.7.18：看图模式下的悬浮（气泡 + 圆点放大）。"""
        item = self.map_view.view_hit_station(scene_pos)
        self.map_view.set_view_hover(item)          # 放大光晕（None = 收掉）
        if item is None:
            if not self.tip.pinned:
                self.tip.hide()
            return
        if self.tip.pinned:
            sid = item.data.get("station_id") or item.data.get("station_name")
            if sid == self.tip.pinned_station_id:
                return                              # 已固定在原站，别动
        global_pos = self.map_view.viewport().mapToGlobal(view_pos)
        self.tip.show_for(global_pos, item.data, self.dm.resolve_images(item.data))

    # ------------------------------------------------------------------
    # 槽：站点 增删改
    # ------------------------------------------------------------------
    def _on_station_clicked(self, station_id: str):
        # ★ v2.6.90：左键单击站点 ⇒ 右侧详情面板顺手展开（藏着的就开回来）
        if not self.info_panel.isVisible():
            self._on_toggle_info_panel()
        self.info_panel.show_station(station_id)
        # ★ v2.6.79：单击站点 → **固定**悬浮气泡：可移入鼠标拖滚动条看多图、
        #   点图看大图。已在固定同一站时忽略（再点空白处/Esc 解除）。
        if self.tip.pinned and self.tip.pinned_station_id == station_id:
            return
        item = self.map_view.station_items.get(station_id)
        if item is not None:
            self.tip.pin_for(QCursor.pos(), item.data,
                             self.dm.resolve_images(item.data), station_id)

    def _on_map_empty_clicked(self):
        """★ v2.6.90：左键单击地图空白（非拖动）⇒ 收起右侧详情面板。"""
        if self.info_panel.isVisible():
            self._on_toggle_info_panel()

    def _on_station_double_clicked(self, station_id: str):
        # v2.4.19：开弹窗之前先把悬浮提示收起来。
        # 它是 Qt.ToolTip 顶层窗口，会盖在模态弹窗上面，看着像"弹窗没出来"。
        self.tip.unpin()                      # ★ v2.6.79：固定态也要一并解除
        self.tip.hide()
        dlg = EditDialog(station_id=station_id, parent=self)
        dlg.save_requested.connect(self._on_dialog_save)
        dlg.exec()

    def _on_station_moved(self, station_id: str):
        # ★ v2.6.88：副站体（云巴/有轨电车的换站点，id 形如「清湖@alt0」）——
        #   坐标写进 alt_bodies[i]，不能 upsert 成假站点；主站 x/y 不动。
        if "@alt" in station_id:
            it = self.map_view.alt_items.get(station_id)
            if not it:
                return
            base, idx_s = station_id.rsplit("@alt", 1)
            try:
                idx = int(idx_s)
            except ValueError:
                return
            rec = self.dm.get_station(base) or {}
            bodies = list(rec.get("alt_bodies") or [])
            if idx >= len(bodies):
                return
            b = dict(bodies[idx])
            b["x"] = round(float(it.pos().x()), 1)
            b["y"] = round(float(it.pos().y()), 1)
            bodies[idx] = b
            self.dm.upsert_station(base, {"alt_bodies": bodies})
            self._save_data()
            # 线路（line_station_xy 读 alt_bodies）+ 虚线/副站体图元都要跟
            self.map_view.rebuild_lines()
            self._refresh_status()
            self.lbl_hint.setText(
                f"已移动「{rec.get('station_name', base)}」副站体 → ({b['x']:.0f}, {b['y']:.0f})")
            return
        item = self.map_view.station_items.get(station_id)
        if not item:
            return
        # 同步坐标到数据
        self.dm.upsert_station(station_id, {
            "x": item.data.get("x"),
            "y": item.data.get("y"),
        })
        self._save_data()
        # 线路要跟着站点走
        self.map_view.rebuild_lines()
        self._refresh_status()
        self.lbl_hint.setText(f"已移动「{item.data.get('station_name', station_id)}」→ ({item.data.get('x'):.0f}, {item.data.get('y'):.0f})")

    def _on_label_moved(self, station_id: str):
        """v2.6.32：站名被单独拖过 —— 把偏移（屏幕像素）写进 stations.json。"""
        item = self.map_view.station_items.get(station_id) or \
            self.map_view.alt_items.get(station_id)
        if not item:
            return
        # ★ v2.6.82：副站体的站名（id 形如「湖贝@alt0」）—— 偏移/方位写进
        #   该站 alt_bodies[i]，不能 upsert 成一条叫「湖贝@alt0」的假站点。
        if "@alt" in station_id:
            base, idx_s = station_id.rsplit("@alt", 1)
            try:
                idx = int(idx_s)
            except ValueError:
                return
            rec = self.dm.get_station(base) or {}
            bodies = list(rec.get("alt_bodies") or [])
            if idx >= len(bodies):
                return
            bodies[idx] = dict(bodies[idx])
            bodies[idx]["label_dx"] = round(item.label_off().x(), 1)
            bodies[idx]["label_dy"] = round(item.label_off().y(), 1)
            bodies[idx]["label_side"] = item.label_side()
            self.dm.upsert_station(base, {"alt_bodies": bodies})
            self._save_data()
            self._refresh_status()
            self.lbl_hint.setText(
                f"已挪动「{item.data.get('station_name', base)}」副站体的站名 "
                f"→ ({item.label_off().x():.0f}, {item.label_off().y():.0f})")
            return
        self.dm.upsert_station(station_id, {
            "label_dx": round(item.label_off().x(), 1),
            "label_dy": round(item.label_off().y(), 1),
            # ★★ v2.6.60：**方位也要一起存**。只存偏移的话，重开时方位回到初始值，
            #   "方位摆位 + 偏移"的基点换了一个 ⇒ 位置差几十像素（用户原话
            #   「每次修改文字位置后再打开会丢失正确位置」）。
            "label_side": item.label_side(),
        })
        self._save_data()
        self._refresh_status()
        self.lbl_hint.setText(
            f"已挪动「{item.data.get('station_name', station_id)}」的站名 "
            f"→ ({item.label_off().x():.0f}, {item.label_off().y():.0f})")

    def _on_toggle_add_mode(self, checked: bool):
        self.map_view.set_add_mode(checked)
        if checked:
            self.lbl_hint.setText("➕ 添加模式开启：地图上点空白处即可新增站点")
        else:
            self.lbl_hint.setText("已退出添加模式")

    def _on_add_station_at(self, scene_pos) -> None:
        # 用弹窗创建，初始坐标就是点击位置
        self.tip.hide()                       # 同上：别让悬浮提示盖住弹窗
        dlg = EditDialog(station_id="", parent=self)
        dlg.save_requested.connect(lambda sid, payload: self._on_dialog_save(sid, payload, scene_pos))
        dlg.exec()
        # 落完一个站就退出添加模式（★ v2.7.16：开关就是「➕ 新建站点」本身）
        self.act_new_station.setChecked(False)

    def _on_dialog_save(self, station_id: str, payload: dict, scene_pos=None) -> None:
        # 如果是新增且给了 scene_pos，注入坐标
        is_new = station_id not in self.dm.all_stations()
        if is_new and scene_pos is not None:
            payload["x"] = round(scene_pos.x(), 1)
            payload["y"] = round(scene_pos.y(), 1)
        if is_new:
            self.dm.upsert_station(station_id, payload)
        else:
            # ★ v2.6.57：改名要重键（站序 / 折点表 / 方块表全跟着换）
            station_id, renamed = self._apply_rename(station_id, payload)
            self.dm.upsert_station(station_id, payload)
            is_new = renamed            # 主键换了 ⇒ 图元也要整体重建

        self._save_data()

        if is_new:
            self.map_view.reload_stations(self.dm.all_stations())
        else:
            self.map_view.update_station(station_id, payload)
        # 线路需要跟着站点走 / 或该站所属线路变了
        self.map_view.rebuild_lines()
        self.legend_panel.set_lines(self.dm.all_lines(), self.dm.all_stations())
        self.info_panel.show_station(station_id)
        self.lbl_hint.setText(f"✓ 已保存「{payload.get('station_name','?')}」")
        self._refresh_status()

    def _on_info_save(self, station_id: str, payload: dict) -> None:
        station_id, renamed = self._apply_rename(station_id, payload)
        self.dm.upsert_station(station_id, payload)
        self._save_data()
        if renamed:
            # ★ 主键换了 ⇒ 地图上图元的 id 也得换，只能整体重建
            self.map_view.reload_stations(self.dm.all_stations())
        else:
            self.map_view.update_station(station_id, payload)
        self.map_view.rebuild_lines()
        self.info_panel.show_station(station_id)
        if not renamed:
            self.lbl_hint.setText("✓ 信息已保存")
        self._refresh_status()

    def _apply_rename(self, station_id: str, payload: dict) -> tuple:
        """改名要**重键**（本工程 `station_id == station_name`），见 `dm.rename_station`。

        返回 `(真正要用的 station_id, 是否真的改名了)`。

        ★ 必须在 `upsert_station` **之前**调：upsert 会把新的 station_name 写进
          记录，之后再 rename 就分不清"哪个是旧名"了。
        ★ 新名和别的站撞了 ⇒ **拒绝改名**、保留旧名，并且**明说为什么**
          （静默吞掉一个站的数据比不改更糟）。
        ★ v2.6.57 之前只改 `station_name` 不动键 ⇒ 名字显示是新的、内部编号
          还是旧的：20 条线的站序、折点方向表、末端方块表里全是旧名。
        """
        # A/B 开关：`METROEDITOR_NO_RENAME=1` 退回"只改名字不重键"的旧行为，
        #   回归 `_chk_rename_station.py` 用它做变异自检。
        if os.environ.get("METROEDITOR_NO_RENAME", "0") == "1":
            return (station_id, False)
        new_name = (payload.get("station_name") or "").strip()
        old = self.dm.get_station(station_id) or {}
        old_name = old.get("station_name", station_id)
        if not new_name or new_name == old_name:
            return (station_id, False)
        if self.dm.rename_station(station_id, new_name):
            return (new_name, True)
        payload["station_name"] = old_name           # 还原，别存半个改名
        self.lbl_hint.setText(
            "⚠ 站名没改成「%s」（已经有同名的站了），已保留「%s」"
            % (new_name, old_name))
        return (station_id, False)

    def _on_info_autosaved(self, station_id: str) -> None:
        """v2.6.57：面板里改了字没点保存就切站/关窗口 —— 已自动兜住，明说一声。

        ★ 必须让用户**看得见**：自动保存如果一点动静都没有，用户仍然会怀疑
          "到底存没存"，下次还是不敢放心改（用户原话「可能不被保存」）。
        """
        st = self.dm.get_station(station_id) or {}
        self.lbl_hint.setText(
            "⚠ 你改了「%s」还没点保存，已自动存好（Ctrl+Z 可撤销）"
            % st.get("station_name", station_id))
        self._refresh_status()

    def _on_delete_current_station(self) -> None:
        """★ v2.7.3：工具栏「🗑 删除站点」—— 删**右侧面板当前显示**的那个站。

        跟地图右键菜单里的"删除该站点"走同一条链路，只是入口从菜单搬到工具栏。
        ★ 没有选中站就**只提示不动作**（弹确认框会吓人，也容易误删）。
        """
        # ★★ 必须**面板正开着**：收起时 `_current_station_id` 还留着上一个站，
        #    照着它删 = 用户看不见要删的是谁，等于盲删。收起状态一律只提示不动作。
        if self.info_panel.isHidden():
            self._toast("先展开右侧详情面板并选中一个站点")
            return
        sid = getattr(self.info_panel, "_current_station_id", None)
        if not sid:
            self._toast("先在地图上点一个站点，再点「删除站点」")
            return
        name = str(sid)
        try:
            d = self.dm.get_station(sid) or {}
            name = str(d.get("station_name") or sid)
        except Exception:
            pass
        r = QMessageBox.question(
            self, "确认删除",
            f"删除站点「{name}」？此操作只删除软件内记录（Ctrl+Z 不一定撤得回）。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self._on_delete_station(sid)
        self._toast(f"已删除站点「{name}」")

    def _on_delete_station(self, station_id: str) -> None:
        self.dm.delete_station(station_id)
        self._save_data()
        self.map_view.remove_station(station_id)
        self.legend_panel.set_lines(self.dm.all_lines(), self.dm.all_stations())
        self.info_panel.show_empty_state()
        self._refresh_status()

    def _on_save_all(self) -> None:
        self._save_data()
        self._refresh_status()
        self.lbl_hint.setText("✓ 已主动保存")

    # ------------------------------------------------------------------
    # 导入 / 导出 / 关于
    # ------------------------------------------------------------------
    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择导入文件（JSON）", str(PROJECT_ROOT),
            "JSON Files (*.json);;All Files (*.*)"
        )
        if not path:
            return
        try:
            # 记事本另存的 JSON 可能带 BOM 或是 UTF-16，交给它猜（见文件顶部的说明）
            content = json.loads(read_text_file_smart(path))
            # 兼容两种格式
            if isinstance(content, dict) and "stations" in content:
                items = content["stations"]
            else:
                items = content
            res = self.dm.bulk_import(items)      # 内部自己落盘
            self._mark_saved()                    # 所以这里只记时刻，别再写一遍
            self.map_view.reload_stations(self.dm.all_stations())
            self.map_view.rebuild_lines()
            self.legend_panel.set_lines(self.dm.all_lines(), self.dm.all_stations())
            self._refresh_status()
            QMessageBox.information(
                self, "导入完成",
                f"新增 {res['added']} 个、更新 {res['updated']} 个、失败 {res['failed']} 个"
            )
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"出错：\n{e}")

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存数据到…", str(PROJECT_ROOT / "data" / "stations_export.json"),
            "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.dm.stations_doc, f, ensure_ascii=False, indent=2)
            self.lbl_hint.setText(f"✓ 已导出到 {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _on_about(self):
        QMessageBox.about(
            self, "关于本软件",
            "<b>深圳地铁线路图编辑器 v2.0</b><br><br>"
            "本软件<b>不依赖任何图片</b>——地图上的线路和站点全部由程序"
            "根据 <code>data/lines.json</code> 和 <code>data/stations.json</code> "
            "实时绘制。<br><br>"
            "<b>交互</b><br>"
            "• 单击站点：右侧面板查看 / 编辑<br>"
            "• 双击站点：弹出大窗口编辑<br>"
            "• 悬浮站点：气泡显示简介<br>"
            "• <b>按住空白处拖动：平移地图</b>（也可按住中键随处拖动）<br>"
            "• 空白处单击：取消选中<br>"
            "• 双击空白处：新增站点<br>"
            "• 拖动站点：调整位置（线路自动跟随）<br>"
            "• 滚轮：缩放<br><br>"
            "<b>站名显示</b><br>"
            "站名加粗并带白色描边，缩小时会按优先级自动避让重叠，"
            "尽可能多地保留站名；换乘站与当前选中站优先显示。<br><br>"
            "<b>键盘</b><br>"
            "• ↑↓←→：同方向最近站点<br>"
            "• Enter：等同双击<br>"
            "• Tab：跳到最近站点<br>"
            "• Esc：取消选择<br><br>"
            "<b>图例</b><br>"
            "• 悬停线路名：高亮该线路<br>"
            "• 单击线路名：缩放到该线路<br><br>"
            "站点数据保存在 <code>data/stations.json</code>，可手动维护或通过 AI 批量导入。"
        )

    # ------------------------------------------------------------------
    # 关闭事件：确保数据已落盘
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        try:
            # ★ v2.6.57：编辑框里改了但**没点保存**的内容，关窗口前先提交掉。
            #   之前这里只 `dm.save()` —— 写的是内存里**已提交**的数据，
            #   编辑框里那些没提交的字照样丢（实测确认）。
            ip = getattr(self, "info_panel", None)
            if ip is not None and hasattr(ip, "flush_pending"):
                ip.flush_pending()
            self.dm.save()
        except Exception as e:
            # ★ v2.7.33：这里以前是 `pass` —— 磁盘满 / JSON 写坏时，用户改了半天的
            #   东西无声丢光，事后一点线索都没有。至少留个痕（控制台 + 崩溃日志）。
            print("[close] 关窗落盘失败，未提交的编辑可能丢失：", repr(e))
            try:
                import traceback
                traceback.print_exc()
            except Exception:
                pass
        # ★ v2.7.14：退出前询问是否把整张图保存为图片（设置里可关）
        # ★ v2.7.32：只有**元素真改过、图已过期**才问。
        #   以前只看"有没有烘过图"，于是"开一下、什么都没动、关掉"也会被问一次（用户反馈）。
        try:
            sec = self._img_settings()
            if sec.get("ask_on_exit", True) and getattr(self, "_view_img", None) is not None:
                if self._img_is_fresh():
                    print("[image_mode] 退出：数据未变、png 已是最新，跳过询问")
                else:
                    from PySide6.QtWidgets import QMessageBox
                    from ui.image_mode import png_path, save_png
                    p = png_path(self._data_dir(), sec)
                    r = QMessageBox.question(
                        self, "退出", f"要不要把整张图保存为图片？\n\n{p}",
                        QMessageBox.Yes | QMessageBox.No)
                    if r == QMessageBox.Yes:
                        save_png(self._view_img, p)
                        self._img_sig_done = self._img_sig_now()
        except Exception as e:
            print("[image_mode] 退出保存失败：", repr(e))
        super().closeEvent(event)
