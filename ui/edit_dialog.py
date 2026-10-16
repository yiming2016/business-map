"""
ui/edit_dialog.py
========================
双击站点弹出的"编辑弹窗"，与 InfoPanel 字段一样，但窗口更大，
multiline 字段更高，按钮更醒目。

  mode = "edit"  -> 编辑现有站点
  mode = "new"   -> 新建站点（不传 station_id）

布局约定（2026-09-18 起）：
  ① **站点名称全窗口只出现一次** —— 就是顶部「[封面图][名称输入框]」里的输入框。
     原来的 `station_id：` 只读行、以及表单里的「站点名称」行都已删除。
  ② 原来「📍 编辑站点：」那行文字换成一个**添加图片的图标按钮**：
     点一下选一张图当封面，鼠标悬浮到地图上该站点时会显示这张图。
     v2.4.10 放大到 76×76；v2.4.11 再翻一倍到 108×108；
     **v2.4.12 改为「底边与简介框底边严格齐平」**——边长不再写死，
     由 `_align_cover_to_desc()` 按实测底边差反推（编辑模式 ≈230、新建 ≈212）。
     实现要点：按钮在行里必须是 `Qt.AlignVCenter`（居中的话底部才随尺寸单调下移），
     且 `setSizePolicy(Fixed, Fixed)`，否则会被布局压扁。
  ③ **站点名称输入框只留"4 个中文字"的宽度**。
     v2.4.13：112 → **80px**（实测 80px 能写 4 字并留 14px 余量、塞不下第 5 字），
     同时把 `setMaxLength(4)` 卡上，避免"框窄但光标还能继续往后敲"。
  ④ 「所属线路」改成**下拉多选**（收起时显示已选，展开才看到全部候选项，
     展开后**一行 3 个**）。
     **v2.4.13：从下面的表单搬到顶部，紧贴在名称框右侧**。
     **v2.4.14：宽度 165 → 205px、分隔符顿号 → 空格**（空格比顿号窄，反而省地方）。
     **v2.4.15：205 → 240px** —— 用户反馈"有概率显示不全四个'号线'"。
     根因：205px 只留 8px 余量，而**真实最坏情况不是岗厦北（156px）**，
     是"4 条两位数线路"`10号线 11号线 12号线 20号线` = **163px**
     （控件内耗实测 34px → 需要 197px）。字体渲染随 DPI/抗锯齿微变就顶出去了。
     240px 下文字可用 206px，余量 43px，连 5 条两位数（205px）都放得下；
     顶栏可用 242px，刚好不用再动窗口宽度。
     表单里那行连"所属线路"四个字标签一起删掉。
  ⑤ **顶部不再显示"简介"两个字**（v2.4.11 删）——简介内容框紧跟名称框，
     靠 placeholder「简介：地理位置、命名由来等…」提示含义。
     名称与简介仍**放在同一个竖排容器里**，所以简介的左边恒与名称框左边对齐，
     封面图再宽也只是把这一整列往右推。  ⑥ 「出入口信息 / 设施 / 周边地标 / 备注」4 个多行字段是**标签在上、输入框在下**。
  ⑦ 名称与简介放进同一个容器后，用 `objectName` + `QWidget#id QLabel{...}` 统一
     调这两处标签的颜色/字号（比逐个 setStyleSheet 更省事，也好统一改）。
  ⑧ **整体圆润**（v2.4.11）：窗口圆角 16px + 浅灰底 #f7f8fa，
     输入框圆角 8px、按钮圆角 10px，滚动条也做成圆头细条。
     ⚠️ 带标题栏的顶层窗口，四个角是**系统画的**，样式表 `border-radius` 对
     窗口本身无效；有 parent 时 Qt 也**不会**自动挖透明（实测被推翻）。
     因此统一由 `_apply_round_region()` 用 Win32 `SetWindowRgn` 手动裁圆，
     **不论有没有 parent 都执行**。
     两个坑：① 尺寸必须取 `GetWindowRect`（物理像素），不能用
     `self.width()*dpr`，否则本进程 DPI-unaware 会被多乘一次、切掉右/下边；
     ② Qt 首次绘制会把窗口区域重置回整矩形，所以只能在
     `showEvent` 里用 `singleShot(0/60)` **延迟**裁，且**不要**在
     `paintEvent` 里重裁。
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt, QSize, QPoint, QRect, Signal, QTimer
from PySide6.QtGui import QFont, QFontMetrics, QIcon
from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QPlainTextEdit, QCheckBox, QPushButton,
    QDialogButtonBox, QScrollArea, QWidget, QFrame,
    QToolButton, QMenu, QFileDialog, QMessageBox, QSizePolicy, QLayout,
    QComboBox,
)

from core.schema import (EDITABLE_FIELDS, new_station_template, derive_is_transfer,
                         HIDDEN_UI_FIELDS, READONLY_UI_FIELDS)
from core.data_manager import get_data_manager
from ui.widgets import LinesSelect, make_add_image_icon, make_cover_icon, make_nursing_icon
from ui.timetable_editor import TimetableEditor
# v2.6.8：表单行的两种形态 + 高度自适应，都抽成了与右侧面板共用的模块
from ui.form_rows import make_stacked, make_inline_row, inject_head
from ui.autofit import AutoFitGroup
from ui.metro_render import icon_pixmap   # v2.6.69：图标按钮/选择页贴图（无环）


IMAGE_FILTER = ("图片 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;"
                "所有文件 (*.*)")

# ============================================================
# 封面图标缓存（v2.4.19）
# ============================================================
# ★ 为什么必须缓存：`make_cover_icon` → `rounded_pixmap` 会**重新读盘 + 解码 +
#   SmoothTransformation 缩放**整张原图。实测：
#     · 640×640 小图  → 0.5 ms（无感）
#     · 4032×3024 手机照片 → **45 ms**
#   而弹窗开场 `_refresh_cover_button` 要跑 4 次（封面图对齐会迭代、且每次
#   迭代都刷新图标）→ 手机照片下光"开场画图标"就 180ms；窗口每次重排还可能再来
#   一轮。缓存后同一张图只解码一次，等于把这些全部省掉。
#   缓存键带上 mtime —— 用户换图、改图后立刻生效，不会显示旧图。
_ICON_CACHE: Dict[tuple, QIcon] = {}


def _cached_cover_icon(src, size: int) -> QIcon:
    """按 (路径, mtime, 尺寸) 缓存封面图标；src 为空则给"添加图片"图标。"""
    if src:
        try:
            mt = Path(str(src)).stat().st_mtime
        except Exception:
            mt = 0.0
        key = ("file", str(src), mt, int(size))
    else:
        key = ("add", 0.0, int(size))

    ic = _ICON_CACHE.get(key)
    if ic is not None:
        return ic

    if src:
        ic = make_cover_icon(src, int(size))
        if ic.isNull():
            ic = make_add_image_icon(int(size))
    else:
        ic = make_add_image_icon(int(size))

    # ★ v2.6.79：多图后一次刷新要解码 N 张，缓存上限 8 会来回抖 —— 提到 64、
    #   满了只淘汰最早的一条（FIFO），不再整表清空。
    if len(_ICON_CACHE) >= 64:
        try:
            _ICON_CACHE.pop(next(iter(_ICON_CACHE)))
        except Exception:
            _ICON_CACHE.clear()
    _ICON_CACHE[key] = ic
    return ic

# 顶部封面图按钮的边长，以及里面缩略图的边长（图标比按钮小一圈留白）
# v2.4.11：按钮面积翻倍（76→108，约 2.02 倍），图标同步放大
# v2.4.12：改为**图片底边与「简介」输入框底边严格齐平**，
#          边长不再手填，由 `_align_cover_to_desc()` 在 showEvent 里按简介框实测高度回填
#          （当前简介框 ≈192px 高 → 按钮 192×192）。
COVER_BTN_SIZE = 192
COVER_ICON_SIZE = 174

# 站点名称输入框宽度：刚好够写 **4 个中文字**。
# 实测（11pt 微软雅黑）：4 字 60px、5 字 75px；框宽 80px 时可用字宽 74px
# → 能写下 4 个字并留 14px 余量，但塞不下第 5 个字。
# v2.4.13：112 → 80 —— 112px 实测能塞 6~7 个字，用户觉得偏宽。
NAME_WIDTH = 80
# 名称的**硬性字符数上限**（光靠框宽不够：光标能继续往后敲，只是看不见）
# ★ v2.6.66：4 → 24。当年站名基本 2~4 字，"机场(T3)"这类带后缀的官方名
#   （6 字符）会被 setMaxLength(4) **静默截断成"机场(T"**——用户原话
#   「『机场』站名为『机场(T3)』，我无法手动修改这个名字」。
#   更糟的是：打开长名站的弹窗直接点保存，会把截断名存回数据。
#   框宽仍是 80px（输入时横向滚动），上限只做防呆不再做排版。
NAME_MAX_CHARS = 24


def _center_until_focus(ed) -> None:
    """站名输入框：**默认居中、编辑时靠左**（v2.7.12）。

    ★ 与 `InfoPanel.title` 同一套观感：居中是"展示态"，一点进来就切 AlignLeft
      让光标从左往右走，失焦再回居中。
    ★ 只换**实例**的虚方法（types.MethodType）——PySide6 里类级补丁不会进
      Python 层的分发表，改了等于没改（v2.6.x 踩过的坑）。
    """
    ed.setAlignment(Qt.AlignCenter)

    def _focus_in(self, ev):
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        QLineEdit.focusInEvent(self, ev)

    def _focus_out(self, ev):
        QLineEdit.focusOutEvent(self, ev)
        self.setAlignment(Qt.AlignCenter)

    ed.focusInEvent = types.MethodType(_focus_in, ed)
    ed.focusOutEvent = types.MethodType(_focus_out, ed)


# 「所属线路」挪到顶栏后给的固定宽度。
# v2.4.14：165 → 205（容纳 4 条线路 + 顿号改空格）。
# v2.4.15：205 → **240** —— 用户反馈"有概率显示不全四个'号线'"。
#   根因：205px 只留了 8px 余量，太紧。控件内耗是**实测**的 34px
#   （样式表 `padding: 4px 24px 4px 8px` + 左右各 1px 边框），
#   而真实最坏情况不是岗厦北（156px），是"4 条两位数线路"：
#       "10号线 11号线 12号线 20号线" = 163px  → 需要 197px
#   字体渲染宽度会随 DPI / 抗锯齿 / 字号微变（这就是"有概率"的来源），
#   8px 余量扛不住。改成 240px：文字可用 206px，对 163px 留了 43px 余量，
#   连"5 条两位数线路"（205px）都放得下。
#   顶栏可用 242px，240px 刚好不用再改窗口宽度。
LINES_WIDTH = 240
# 控件"内耗"宽度（左右 padding + 边框），实测量得，别改小
LINES_INNER_PAD = 34

# v2.6.68：顶栏「所属区」下拉 —— 放到「所属线路」右侧，**"所属区"四个字删掉**。
#   3 个字（"福田区"/"不设置"）11pt 雅黑 ≈ 44px + 下拉箭头/内耗 ≈ 34px → 88px 足够。
DISTRICT_WIDTH = 88
# v2.6.69/70：图标标签行（多组「图标按钮 + 上/下/左/右 + 文字」）
#   v2.6.70：下拉换成**图标按钮**，点击弹出表情包式选择页（ICON_CATALOG 网格）。
#   3 组宽 = 3×(30+2+22+4+110) + 2×12 ≈ 528px ≤ 弹窗内宽 732px。
TAG_SLOT_COUNT = 3
# v2.6.70：图标目录（选择页网格）。hotel_* 四色楼房与 mall_* 级别对应一致：
#   红=一级(S) 金=二级(A) 紫=三级(B) 绿=四级(C)
ICON_CATALOG = [
    ("", "无"),
    ("hsr", "🚄 高铁站"),
    ("airport", "✈️ 机场"),
    ("mall_red", "红袋·商场一级"),
    ("mall_gold", "金袋·商场二级"),
    ("mall_purple", "紫袋·商场三级"),
    ("mall_green", "绿袋·商场四级"),
    ("hotel_red", "红楼·酒店一级"),
    ("hotel_gold", "金楼·酒店二级"),
    ("hotel_purple", "紫楼·酒店三级"),
    ("hotel_green", "绿楼·酒店四级"),
    ("mansion_red", "豪宅一级（红）"),
    ("mansion_gold", "豪宅二级（金）"),
    ("mansion_purple", "豪宅三级（紫）"),
    ("mansion_green", "豪宅四级（绿）"),
]

# v2.6.71：每个图标的**含义原文**（用户两份分级清单的"说明"节选），
#   鼠标悬浮在编辑页的图标按钮 / 选择页图标上时以 tooltip 显示。
#   首行是目录里的短名，第二行起是级别释义；"\n" 在 QToolTip 里正常换行。
ICON_MEANINGS = {
    "hsr": "高铁站：标注原图中的高铁枢纽站",
    "airport": "机场：标注宝安国际机场",
    "mall_red": "商场一级（S级）：城市顶级购物中心"
                "（高端地标，辐射全市及大湾区）",
    "mall_gold": "商场二级（A级）：区域核心综合商场"
                 "（10万㎡以上全业态，辐射跨行政区）",
    "mall_purple": "商场三级（B级）：片区中型购物中心"
                   "（5-10万㎡，服务单个行政区内片区）",
    "mall_green": "商场四级（C级）：社区便民/主题商业"
                  "（5万㎡以下，社区配套或主题街区）",
    "hotel_red": "酒店一级（S级·顶奢奢华）：国际顶级奢华品牌，"
                 "城市地标级旗舰物业",
    "hotel_gold": "酒店二级（A级·豪华五星）：国际高端五星旗舰/本土顶级五星标杆，"
                  "配置高于常规五星",
    "hotel_purple": "酒店三级（B级·标准五星）：正规挂牌五星/国际标准五星连锁，"
                    "商务度假主流五星",
    "hotel_green": "酒店四级（C级·高端准五星）：高端商务精品/准五星定位，"
                   "品质优于普通商务酒店",
    # v2.6.76：豪宅含义换成清单原文（70年商品住宅+地铁口步行≤800米）
    "mansion_red": "豪宅一级（S级·顶奢标杆级）：单价15万/㎡以上",
    "mansion_gold": "豪宅二级（A级·高端豪宅级）：单价10-15万/㎡",
    "mansion_purple": "豪宅三级（B级·改善豪宅级）：单价7-10万/㎡",
    "mansion_green": "豪宅四级（C级·准高端潜力级）：单价6-7万/㎡",
}


def _icon_tooltip(val: str) -> str:
    """图标值 → 悬浮提示全文（短名 + 含义原文；空值/未知值给短名）。"""
    val = str(val or "")
    lab = next((l for v, l in ICON_CATALOG if v == val), val)
    mean = ICON_MEANINGS.get(val)
    if mean and val:
        return f"{lab}\n{mean}"
    return lab or "点击选择图标"
TAG_POS_ITEMS = [
    ("left", "图标在文字左边"),
    ("top", "图标在文字上方"),
    ("right", "图标在文字右边"),
    ("bottom", "图标在文字下方"),
]
TAG_POS_OPTIONS = tuple(p for p, _ in TAG_POS_ITEMS)
# v2.6.85：四个方向收进**一个框**——框上显示当前方向字，点框弹菜单改
TAG_POS_CHARS = {"top": "上", "bottom": "下", "left": "左", "right": "右"}
TAG_POS_MENU_ORDER = ("top", "bottom", "left", "right")   # 菜单顺序：上、下、左、右
TAG_BTN_SIZE = 30          # 图标按钮边长（点击弹出选择页）
TAG_TEXT_W = 110
TAG_POS_BOX_W = 26         # 方向框宽（高=TAG_BTN_SIZE 同图标按钮对齐）
TAG_GROUP_GAP = 12
# v2.6.87：组内三件套间距（旧实际 13/16px 的 60%）
TAG_GAP_ICON_POS = 8       # 图标按钮→方向框
TAG_GAP_POS_TEXT = 10      # 方向框→文字输入框

# v2.6.4：`same_row` 单行行里**标签的 fixed 宽度**（见 `_make_inline_row`）。
# 手写表单的标签（FormHost 里统一 12px 灰色）最宽是"周边地标"= 4 个中文字 ≈ 48px，
# 给 56px 留点余量；同一列的所有标签宽度一致 ⇒ 输入框左边缘才对得齐。
INLINE_LABEL_W = 56

# v2.6.8：多行输入框"自动拉伸"的**下限高度**（文字再少也不短于这个）。
# · 普通字段 40px ≈ 一行 + 上下留白；
# · 简介 140px —— ★ 右边**封面图的边长是跟着简介框走的**
#   （`_align_cover_to_desc` 按简介框实测底边反推），简介一矮封面图就跟着缩成
#   一小块。140px 大约 3 行，够放一段正常的站点简介，也让封面图不至于变形。
#   长文字照样往上长（这才是"自动拉伸"真正要解决的问题）。
AUTOFIT_MIN_H = 40
AUTOFIT_DESC_MIN_H = 140

# 窗口圆角 & 控件圆角（"整个窗口变得圆润一些"）
WINDOW_RADIUS = 16
FIELD_RADIUS = 8
BTN_RADIUS = 10

# 弹窗初始尺寸。
# v2.4.14：宽 560 → 600 —— 顶栏要给「4 条线路」的下拉（205px）腾地方。
#   右列可用宽 = 弹窗宽 − 左右边距(14×2) − 封面图(230) − 列间距(12)
#     560 → 290px，放 205+80+8=293 差 3px 会挤；600 → 330px，宽松。
# **v2.6.3：600×680 → 760×880**（用户："增宽增长这个编辑页面"）。
#   ① 字段从 9 个涨到 11 个（新增 首末班车 / 公交换乘），680 高根本装不下，
#      滚动区只剩一点点，等于"每改一个字段都要滚"。
#   ② 出入口改成「编号 + 内容」两栏后，编号列要吃掉 46+8px，
#      600 宽下右侧内容区只剩 ~490px，长出口（30+ 字）会被挤成三四行。
#   ③ 顶栏可用宽 = 760 − 28 − 封面(230) − 12 = **490px**，
#      需要 80(名称) + 8 + 240(线路) = 328px，富余很多，不会挤。
# ★ 出场时会再按**当前屏幕可用区**夹一次（见 `_clamp_size_to_screen`），
#   小屏（如 1366×768）不会一出场就顶出屏幕。
DIALOG_WIDTH = 760
DIALOG_HEIGHT = 880

# ============================================================
# 出入口「编号 + 内容」两栏（v2.6.3）
# ============================================================
# 用户要求：把 `A1出入口：龙岗大道南侧、xxx` 里的 **A1 拿出来加粗加大字号**、
# **从输入框独立出去**，并**删掉"出入口"三个字** → 变成
#
#       A1   龙岗大道南侧、xxxxxxxx
#
# 存储格式**不变**（仍是 `A1出入口：xxx`），只在 UI 上拆开显示、保存时拼回去 ——
# 这样不用迁移 379 站的数据，也不影响导入脚本。
#
# ★ 编号列用 **QLineEdit 但画成标签的样子**（无边框、透明底、可聚焦）。
#   为什么不用 QLabel：QLabel 不能编辑，用户就没法改编号、也没法补一个出口。
#   为什么不用普通输入框：那就还是"一个输入框"，没有"独立出去"的观感。
# 走专用 UI 展示的字段（**存储格式都不变**，只是 UI 结构化）：
#   exits     → 「编号 + 内容」两栏（v2.6.3）
#   timetable → 「日期类型分组 + 线路/方向/首班/末班」表格（v2.6.4）
EXITS_KEY = "exits"
TIMETABLE_KEY = "timetable"
# ★ v2.6.5：出入口的两栏编辑器已抽成独立控件 `ui/exits_editor.py`，
#   编辑弹窗与**右侧信息面板共用同一份**（同一字段两份代码 = 同一个 bug 修两遍）。
#   下面这些常量从那里转出来，是为了让本文件里残存的引用不至于失效。
from ui.exits_editor import (                                   # noqa: E402
    ExitsEditor, EXIT_TAG_W, EXIT_TAG_PT, EXIT_TAG_QSS,
    EXIT_SUFFIX, EXIT_ROW_RE, EXIT_ROW_RE_CN, EXIT_ROW_RE2, EXIT_ROW_RES,
    EXIT_TAG_MAX_CHARS, EXIT_TAG_MAX_W,
)

# ==== 并排行（v2.4.17：文字与输入框挤在**同一行**）====
# 并排行里「单行输入框」的固定宽度。给固定值而不是让它跟窗口拉长，
# 否则整排会被拉伸变形、也看不出"两组字段"的分界。
# 180px 够写 `2011-06-22`（10 字符）和 `建设中`（3 个汉字）。
# v2.4.18：180 → **320px**（用户："开通日期的输入框变长一些"）。
#   实测表单可用宽 544px，并排行只占 356px，**余 188px** ——
#   所以 320px 仍在表单内（整排 496px ≤ 544px），**不用改窗口宽度**。
LINE_EDIT_WIDTH = 320
# 两组字段之间的横向间隔（用一个固定宽度的空网格列实现，比调 spacing 更精确）
PAIR_GAP = 26

# 弹窗整体样式：圆角面板 + 浅灰底 + 圆润的输入框 / 按钮
DIALOG_QSS = f"""
QDialog#EditDialog {{
    background: #f7f8fa;
    border: 1px solid #d8dce3;
    border-radius: {WINDOW_RADIUS}px;
}}
QLineEdit, QPlainTextEdit {{
    border: 1px solid #c8ccd4;
    border-radius: {FIELD_RADIUS}px;
    padding: 4px 6px;
    background: #ffffff;
    selection-background-color: #bbdefb;
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: #1976d2; }}
QPushButton {{
    border-radius: {BTN_RADIUS}px;
    padding: 6px 18px;
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px 2px 2px 0;
}}
QScrollBar::handle:vertical {{
    background: #c8ccd4; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #a8b0bb; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""


class EditDialog(QDialog):
    save_requested = Signal(str, dict)  # 发出 (station_id, payload)

    # 供测试/外部引用（同时也是默认值）
    COVER_BTN_SIZE = COVER_BTN_SIZE
    COVER_ICON_SIZE = COVER_ICON_SIZE
    NAME_WIDTH = NAME_WIDTH
    NAME_MAX_CHARS = NAME_MAX_CHARS
    LINES_WIDTH = LINES_WIDTH
    LINES_INNER_PAD = LINES_INNER_PAD
    WINDOW_RADIUS = WINDOW_RADIUS
    BTN_RADIUS = BTN_RADIUS
    LINE_EDIT_WIDTH = LINE_EDIT_WIDTH
    PAIR_GAP = PAIR_GAP

    def __init__(self, station_id: str = "", parent=None):
        super().__init__(parent)
        self._station_id = station_id
        self.is_new = not bool(station_id)
        # ★ 标题文字已经不显示了（v2.6.3），但 windowTitle 仍保留 ——
        #   日志/看门狗要用它区分"编辑/新建"，别顺手删。
        self.setWindowTitle("编辑站点" if not self.is_new else "新建站点")
        self.resize(DIALOG_WIDTH, DIALOG_HEIGHT)
        self._clamp_size_to_screen()

        # ★ v2.4.16：去掉**系统标题栏**，改用自己画的标题栏。
        #   用户要求"鼠标悬浮到 ❌ 时光标变抓手"——系统画的关闭按钮
        #   是 OS 非客户区，Qt 根本收不到它的鼠标事件，光标改不了。
        #   要能改就只能自己画一个 ❌（代价：标题栏外观由我们负责，
        #   且要自己实现拖动窗口）。
        #   注意：窗口是 FramelessWindow 后，Win32 的 SetWindowRgn 圆角裁剪
        #   **仍然要**做（Qt 自己不会给无边框窗口挖透明，除非再加
        #   WA_TranslucentBackground —— 那会带来整窗半透明/阴影的连锁问题，
        #   所以我们沿用已经调通的 SetWindowRgn 方案）。
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self._drag_pos = None

        # 圆润外观：
        #   · 有父窗口时走 Qt 自带的圆角（FreeStyle 会自己把四角挖成透明）
        #   · 没有父窗口（独立弹窗 / 截图）时 Qt 帮不上忙，
        #     由下面的 showEvent 手动 SetWindowRgn 把四角裁圆
        self.setObjectName("EditDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(DIALOG_QSS)

        # 先把数据取出来：顶部控件和下面的表单共用同一份
        dm = get_data_manager()
        if self.is_new:
            self._data = new_station_template()
        else:
            self._data = dm.get_station(self._station_id) or new_station_template()

        # ★ v2.6.79：封面图升级为**多图**。
        #   _img_entries —— [{'name': 已在 covers/ 的文件名 | '', 'src': 本次新选的本地路径 | ''}]
        #   旧的 `cover`（单张）自动当作第一张，数据不丢。
        self._img_entries: list = []
        _names = list(self._data.get("images") or [])
        _cov = str(self._data.get("cover") or "").strip()
        if not _names and _cov:
            _names = [_cov]
        for _n in _names:
            self._img_entries.append({"name": str(_n), "src": ""})

        root = QVBoxLayout(self)
        # ★ v2.6.3：顶部边距 14 → 8（"整体内容往上"）。
        #   原来上面还压着一条 ~28px 的标题栏（"编辑站点" + ✕），现在标题文字整行删掉、
        #   ✕ 改成悬浮（不占布局高度），只剩一条 8px 的拖动条 → 净上移约 22px。
        root.setContentsMargins(14, 8, 14, 14)
        root.setSpacing(10)

        # ---------------- 顶部（v2.6.3：不再有标题文字）----------------
        # 用户："删除文字'编辑站点'，整体内容往上"。
        #   ① 标题文字 `title_lbl` 整个删掉（原来占 ~26px 高）；
        #   ② ✕ **不再进布局**，改成浮在右上角（parent 直接是弹窗，见 `_layout_close_btn`），
        #      这样它一毫米布局高度都不占；
        #   ③ 拖动窗口的能力改由下面这条 **8px 透明条** 承担 ——
        #      ★ 不能图省事把拖动能力整个去掉：无边框窗口只能靠拖特定区域移动，
        #        一旦被拖到屏幕外就再也抓不回来，而主窗口此刻正被模态弹窗禁用，
        #        用户点哪儿都没反应，看起来就是"程序未响应"（v2.4.19 踩过）。
        root.addWidget(self._build_drag_strip())
        self._build_close_button()

        # ---------------- 顶部：封面图（大） +（站点名称 / 简介）----------------
        # 左侧大封面图按钮，右侧竖着摞【站点名称输入框 → 简介】。
        # 这样"简介"在竖直方向上就跟着站点名称走（而不是从封面图左边开始）。
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        # ★ v2.6.79：左侧大封面图按钮 → **多图缩略图条**（可滚动）。
        #   · 每张缩略图：左键看大图、右键菜单（查看大图 / 移除此图）；
        #   · 末尾一枚 ＋ 格子：多选添加本地图片（保存时才拷进 covers/）；
        #   · 外框仍是方形（尺寸由 _align_cover_to_desc 跟简介框底边对齐），
        #     里面 3 列网格 + 纵向滚动，空间利用与原大封面图一致。
        self.cover_strip = QScrollArea()
        self.cover_strip.setWidgetResizable(True)
        self.cover_strip.setFrameShape(QFrame.NoFrame)
        self.cover_strip.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cover_strip.setStyleSheet("""
            QScrollArea { border: 1px solid #c8ccd4; border-radius: 8px; background: #fff; }
            QScrollArea:hover { border-color: #1976d2; }
        """)
        self.cover_host = QWidget()
        self.cover_grid = QGridLayout(self.cover_host)
        self.cover_grid.setContentsMargins(6, 6, 6, 6)
        self.cover_grid.setSpacing(6)
        self.cover_strip.setWidget(self.cover_host)
        # 占位尺寸；showEvent 后 _align_cover_to_desc 会按简介框高度回填
        self.cover_strip.setFixedSize(COVER_BTN_SIZE, COVER_BTN_SIZE)
        self.cover_strip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # ★ v2.4.12：用 **AlignVCenter 不是 AlignTop**。
        #   右列（名称框 + 简介框）总高恒 > 封面按钮，而名称框又必须停在最上面，
        #   所以对右列做垂直居中 ≈ 把按钮往下推，推到"按钮上下留白均等"，
        #   即 **按钮底边 ≈ 简介框底边**。再用 _align_cover_to_desc() 微调到精确齐平。
        top_row.addWidget(self.cover_strip, 0, Qt.AlignVCenter)

        # 右边的竖排：名称 + 简介
        # 容器给个 objectName，用一条作用域样式表统管这两个标签
        self.header_right = QWidget()
        self.header_right.setObjectName("HeaderRight")
        self.header_right.setStyleSheet("""
            QWidget#HeaderRight QLabel { color: #666; font-size: 12px; }
        """)
        right_col = QVBoxLayout(self.header_right)
        right_col.setSpacing(4)
        right_col.setContentsMargins(0, 0, 0, 0)

        self.name_edit = QLineEdit(str(self._data.get("station_name") or ""))
        self.name_edit.setFont(QFont("Microsoft YaHei", 11))
        # 名称框只留 **4 个中文字** 的宽度（不再拉满整行）
        self.name_edit.setFixedWidth(NAME_WIDTH)
        self.name_edit.setMinimumHeight(34)
        # ★ v2.7.12：与右侧面板同一套观感 —— 站名**默认居中显示**，
        #   点进来（获得焦点）才切回靠左、光标从左往右；失焦再居中。
        #   （用户原话「双击的弹窗下站点文字未居中」）
        _center_until_focus(self.name_edit)
        # v2.4.13：真的把**输入上限**也卡到 4 个字（原来只收窄了框宽，
        # 光标一直往后跑还能继续敲，视觉上像"能输 6 个字"）
        self.name_edit.setMaxLength(NAME_MAX_CHARS)

        # v2.4.13：「所属线路」从下面的表单里搬上来，紧贴在名称框右侧。
        # 原表单那行（含"所属线路"四个字标签）整个删掉。
        all_lines = get_data_manager().all_lines()
        self.lines_select = LinesSelect(all_lines, self._data.get("lines") or [])
        self.lines_select.setFixedWidth(LINES_WIDTH)
        self.lines_select.setMinimumHeight(34)

        # 名称框 + 线路下拉 并排一行，一起靠左
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(8)
        name_row.addWidget(self.name_edit, 0, Qt.AlignLeft)
        name_row.addWidget(self.lines_select, 0, Qt.AlignLeft)

        # ★ v2.6.68：「所属区」下拉搬到顶栏「所属线路」右侧（"所属区"四个字删掉，
        #   含义靠选中值自明 —— 下拉里永远显示"福田区"这类区名或"不设置"）。
        district_fld = next(f for f in EDITABLE_FIELDS if f["key"] == "district")
        self.district_combo = QComboBox()
        for _v, _l in district_fld.get("options") or []:
            self.district_combo.addItem(_l, _v)
        _cur = str(self._data.get("district") or "")
        _i = self.district_combo.findData(_cur)
        self.district_combo.setCurrentIndex(_i if _i >= 0 else 0)
        self.district_combo.setFixedWidth(DISTRICT_WIDTH)
        self.district_combo.setMinimumHeight(34)
        name_row.addWidget(self.district_combo, 0, Qt.AlignLeft)

        # ★ v2.7.0：母婴室标记 —— 「所属区」下拉右侧的奶嘴小图标，
        #   仅当该站 facilities 里含「母婴室」时显示（与右侧详情面板同一套图标）。
        self.lbl_nursing = QLabel()
        self.lbl_nursing.setPixmap(make_nursing_icon(20).pixmap(20, 20))
        self.lbl_nursing.setFixedSize(22, 22)
        self.lbl_nursing.setToolTip("本站设有母婴室")
        self.lbl_nursing.setVisible("母婴室" in str(self._data.get("facilities") or ""))
        name_row.addWidget(self.lbl_nursing, 0, Qt.AlignLeft)

        name_row.addStretch()
        right_col.addLayout(name_row)

        # v2.4.11：顶部不再显示"简介"两个字（标签已删），
        # 简介内容框直接跟在名称框下面；字段含义靠 placeholder 提示。
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setPlaceholderText("简介：地理位置、命名由来等…")
        self.desc_edit.setPlainText(str(self._data.get("description") or ""))
        # v2.6.8：高度跟着内容走（下限 140 —— 封面图的边长是跟着它算的，
        #   太矮会把封面图一起压小，原因见 AUTOFIT_DESC_MIN_H 的注释）。
        self._autofit = AutoFitGroup(min_h=AUTOFIT_MIN_H)
        self._autofit.add(self.desc_edit, min_h=AUTOFIT_DESC_MIN_H)
        right_col.addWidget(self.desc_edit)

        if self.is_new:
            hint = QLabel("先填信息，保存后再到地图上拖动到正确位置")
            hint.setStyleSheet("color:#888;font-size:11px;")
            right_col.addWidget(hint)

        top_row.addWidget(self.header_right, 1, Qt.AlignTop)
        root.addLayout(top_row)

        self._refresh_cover_strip()

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#e0e0e0;")
        root.addWidget(sep)

        # v2.6.3：出入口「编号 + 内容」两栏的行表 / 容器。
        # ★ 必须在 `_build_form()` **之前**就存在：`_relayout_exit_rows()` 会被
        #   showEvent/resizeEvent 早于表单构造调用到（拿不到就当没有出入口行）。
        self._exit_rows: list = []
        self._exit_form_widget = None

        # 顶部这几个控件登记进字段表，_collect() 才能取到
        self._widgets: Dict[str, QWidget] = {
            "station_name": self.name_edit,
            "description": self.desc_edit,
            "lines": self.lines_select,
            "district": self.district_combo,   # v2.6.68：所属区下拉在顶栏
        }

        # ---------------- 滚动表单 ----------------
        self.form_host = QWidget()
        # 用作用域选择器统管所有表单标签的样式（跨列表单行里的 QLabel 也能命中）
        self.form_host.setObjectName("FormHost")
        self.form_host.setStyleSheet("""
            QWidget#FormHost QLabel { color: #666; font-size: 12px; }
        """)
        self.form_layout = QFormLayout(self.form_host)
        # 标签与整块表单都**居左**（原来是标签右对齐 + 表单块居中，
        # 视觉上会往右缩进一大截）
        self.form_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.form_layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form_host)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, 1)

        # ---------------- 按钮 ----------------
        # 只留"保存"。取消走窗口右上角的 ✕（或按 Esc），
        # QDialog 默认就会把关闭/Esc 当成 reject。
        button_box = QDialogButtonBox()
        self.btn_save = button_box.addButton("💾 保存", QDialogButtonBox.AcceptRole)
        # v2.4.16：鼠标悬浮到"保存"上时光标变**抓手**（跟封面图按钮一致）
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet(
            f"QPushButton{{background:#1976d2;color:white;padding:7px 22px;"
            f"border:none;border-radius:{BTN_RADIUS}px;font-weight:bold;}}"
            "QPushButton:hover{background:#1565c0;}"
            "QPushButton:pressed{background:#0d47a1;}"
        )
        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self.reject)
        root.addWidget(button_box)

        self._build_form()
        # ★ 构造完就先把 ✕ 摆好。`resize()` 对**还没上屏**的窗口不一定送 resizeEvent，
        #   只靠 showEvent/resizeEvent 的话，构造完那一刻 ✕ 还停在 (0,0)
        #   （回归测试量到右边距 735px —— 一眼看出没摆）。
        self._layout_close_btn()

    # ============================================================
    # 顶部：极窄拖动条 + 悬浮 ✕（v2.6.3，替代 v2.4.16 的自绘标题栏）
    # ============================================================
    def _build_drag_strip(self) -> QWidget:
        """一条 8px 高的透明条，专门用来**拖动窗口**（不显示任何东西）。

        为什么还要留：见 `__init__` 里第 ③ 条的说明 —— 无边框窗口必须有可拖区域，
        否则拖出屏幕就抓不回来了。8px 是为了"看不出来"，但有总比没有好。
        """
        bar = QWidget()
        bar.setObjectName("DragStrip")
        bar.setFixedHeight(8)
        bar.setCursor(Qt.SizeAllCursor)          # 光标提示"这里能拖"
        bar.setToolTip("拖动窗口")
        bar.mousePressEvent = self._title_mouse_press
        bar.mouseMoveEvent = self._title_mouse_move
        bar.mouseReleaseEvent = self._title_mouse_release
        self._title_bar = bar
        return bar

    def _build_close_button(self) -> None:
        """右上角 ✕ —— **parent 是弹窗本身、不进任何布局**，靠 `move()` 定位。

        ★ 为什么必须浮动：它一进布局就要占一行（≈26px），而用户要的是
          "删掉标题文字、内容整体上移"。
        ★ 位置必须在**每次尺寸变化后**用**当前**宽高重算（见 `_layout_close_btn`），
          手写一次 `move()` 会读到上一帧的尺寸 → 连续 resize 会一路漂
          （同一个坑见 MEMORY §4.3：车厢卡片那次漂到了 x=-240）。
        """
        self.btn_close = QToolButton(self)       # ★ parent=self，不进布局
        self.btn_close.setObjectName("CloseButton")
        self.btn_close.setText("✕")
        self.btn_close.setCursor(Qt.PointingHandCursor)   # ★ 用户要的抓手
        self.btn_close.setToolTip("关闭")
        self.btn_close.setFixedSize(26, 26)
        self.btn_close.setStyleSheet("""
            QToolButton#CloseButton {
                border: none; border-radius: 13px;
                background: transparent; color: #8a8f99;
                font-size: 15px; font-weight: bold;
            }
            QToolButton#CloseButton:hover { background: #e81123; color: #fff; }
            QToolButton#CloseButton:pressed { background: #c50f1f; color: #fff; }
        """)
        self.btn_close.clicked.connect(self.reject)

    def _layout_close_btn(self) -> None:
        """把 ✕ 摆到右上角（用**当前**尺寸算，不缓存坐标）。"""
        b = getattr(self, "btn_close", None)
        if b is None:
            return
        # 右边距 12、上边距 6 —— 和圆角(16px)保持一点呼吸，别贴着拐角
        b.move(self.width() - b.width() - 12, 6)
        b.raise_()                                # 压在最上层，别被内容盖住

    def _title_mouse_press(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            ev.accept()

    def _title_mouse_move(self, ev):
        if self._drag_pos is not None and (ev.buttons() & Qt.LeftButton):
            self.move(self._clamp_to_screen(ev.globalPosition().toPoint() - self._drag_pos))
            ev.accept()

    def _clamp_to_screen(self, pos) -> QPoint:
        """把窗口位置夹到"标题栏至少露一截"的范围里。

        ★ v2.4.19 新增。为什么需要：去掉系统标题栏后窗口**只能**靠拖标题栏移动，
          一旦整个窗口被拖到屏幕外，就再也抓不回来了 —— 而主窗口此时正被
          模态弹窗禁用，用户点哪儿都没反应，看起来就是"程序未响应"，只能强杀。
          这里保证：顶部至少留 28px、左右各至少留 120px 可见。
        """
        try:
            from PySide6.QtWidgets import QApplication
            scr = (QApplication.screenAt(pos + QPoint(40, 12))
                   or QApplication.screenAt(self.frameGeometry().center())
                   or QApplication.primaryScreen())
            if scr is None:
                return pos
            a = scr.availableGeometry()
            x = max(a.left() - self.width() + 120, min(pos.x(), a.right() - 120))
            y = max(a.top(), min(pos.y(), a.bottom() - 28))
            return QPoint(int(x), int(y))
        except Exception:
            return pos

    def _title_mouse_release(self, ev):
        self._drag_pos = None

    # ============================================================
    # 圆角窗口（有标题栏的顶层窗口，样式表 border-radius 管不到四角）
    # ============================================================
    def showEvent(self, event):
        super().showEvent(event)
        # ★★ v2.4.19：无边框弹窗必须**自己抢前台**，否则会被主窗口盖住。
        #   为什么：去掉系统标题栏（FramelessWindowHint）之后，Windows 的
        #   "自动把新窗口带到最前"就不可靠了；而本弹窗是**模态**的 ——
        #   它会禁用主窗口。于是"弹窗藏在主窗口后面"的表现就是：
        #   主窗口点不动、键盘打不进字，用户当然只会看到"未响应"。
        #   这里显式 raise_ + activateWindow，并补一次（单次调用有时会被
        #   窗口管理器的 z-order 竞态压回去）。
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self._bring_to_front)
        QTimer.singleShot(80, self._bring_to_front)

        # 首次上屏时 Qt 会把窗口区域重置回整块矩形，
        # 所以要**等它画完第一帧**再裁；早期版本只在这里裁一次会立刻被弹回来。
        self._schedule_round_region(delay=0)
        self._schedule_round_region(delay=60)
        # ★ v2.4.12：封面图边长要在**布局定型之后**才能量准（简介框高度是算出来的），
        #   所以和圆角一样延后到事件循环里做。
        self._schedule_align()
        # ★ v2.6.3：出入口行的高度要按**实际可用宽度**算（未布局时宽度是默认值 100，
        #   算出来的行高完全不对），所以同样延后到布局定型之后。
        self._schedule_exit_rows()
        # ★ v2.6.8：多行输入框的高度同样要等**布局定型**才能量准
        #   （`fit_height` 在未布局时会直接放弃，见 ui/autofit.py 的说明）。
        QTimer.singleShot(0, self._autofit.sync)
        self._layout_close_btn()

    def _bring_to_front(self) -> None:
        """把弹窗提到最前并抢焦点（见 showEvent 的说明）。"""
        try:
            self.raise_()
            self.activateWindow()
        except Exception:
            pass
        # 记一行日志：以后真卡住时，日志里能看出"当时弹窗到底有没有显示/在最前"
        try:
            from core import watchdog
            g = self.geometry()
            watchdog.note(
                f"弹窗置前 {type(self).__name__} visible={int(self.isVisible())} "
                f"active={int(self.isActiveWindow())} "
                f"geom=({g.x()},{g.y()},{g.width()}x{g.height()})")
        except Exception:
            pass

    def _schedule_align(self) -> None:
        """排队做一次封面图对齐（★ 合并同帧内的重复请求）。

        没有这个合并的话，用户拖窗口边缘时每一次 resize 都会排一次
        `_align_cover_to_desc`，而它内部还会再递归排 4 次 —— 一下子堆出
        几十上百个回调，每个都要重算布局，界面就会明显发顿。
        """
        if getattr(self, "_align_queued", False):
            return
        self._align_queued = True

        def run():
            self._align_queued = False
            self._align_cover_to_desc()
        QTimer.singleShot(0, run)

    def _clamp_size_to_screen(self) -> None:
        """把初始尺寸夹进**当前屏幕的可用区**（v2.6.3）。

        为什么需要：弹窗加宽加高到 760×880 后，小屏（1366×768 的可用高只有 ~700）
        会一出场就顶出屏幕下沿 —— 而这是**无边框**窗口，底下那一截既点不到
        也拖不回来。这里按屏幕可用区等比收一点，保证整体可见。
        """
        try:
            from PySide6.QtWidgets import QApplication
            scr = (QApplication.screenAt(self.geometry().center())
                   or QApplication.primaryScreen())
            if scr is None:
                return
            a = scr.availableGeometry()
            # 上下左右各留 24px，别贴边
            w = min(self.width(), max(420, a.width() - 48))
            h = min(self.height(), max(360, a.height() - 48))
            if (w, h) != (self.width(), self.height()):
                self.resize(int(w), int(h))
        except Exception:
            pass      # 拿不到屏幕信息就按默认尺寸，不影响功能

    # ============================================================
    # 出入口：「编号 + 内容」两栏（v2.6.3）
    # ============================================================
    @staticmethod
    def _parse_exit_line(s: str) -> tuple:
        """拆一行 → (编号, 内容, 原样前缀)。

        · `A1出入口：xxx`   → ("A1", "xxx", "A1出入口")
        · `6A号出入口：xxx`  → ("6A", "xxx", "6A号出入口")   ← "号"留在前缀里
        · `北端出入口（连接…）：xxx` → ("北端", "（连接…）：xxx", "北端出入口")
        · `9出入口`         → ("9",  "",    "9出入口")
        · `xxx`（没有编号） → ("",   "xxx", "")

        ★ v2.6.5：实现已搬到 `ui/exits_editor.py`，弹窗与右侧面板共用一份。
        """
        return ExitsEditor.parse_line(s)

    @classmethod
    def _parse_exits(cls, text) -> list:
        """见 `ui/exits_editor.py::ExitsEditor._parse`（同样只有一份实现）。"""
        return ExitsEditor._parse(text)

    def _make_exits_editor(self, value) -> QWidget:
        """整块出入口编辑器：每行 = [编号(大字加粗)] + [内容]。

        ★ v2.6.5：真正实现在 `ui/exits_editor.py::ExitsEditor`。
          这里只做两件事：
          ① `self._exit_rows = ed.rows` —— **保持这个别名**，
             回归测试（`_test_edit_dialog.py`）与 `_collect_exits()` 都读它；
          ② 记下 `self._exit_form_widget`，供 `＋添加出入口` 定位。
        """
        # ★ v2.7.5：编号升级成**按钮**（点一下才能改编号），详细信息是**可编辑
        #   的输入框**，「＋ 添加出入口」按钮也回来了（只读态不建，可编辑态建）。
        #   v2.7.4 那版"只读展示"作废 —— 用户要的是能改，不是只能看。
        ed = ExitsEditor(value)
        self._exit_form_widget = ed
        self._exit_rows = ed.rows          # 同一个 list 对象 ⇒ 新增行自动同步
        self._exit_add_btn = ed._add_btn
        return ed

    @staticmethod
    def _calc_exit_tag_width(tags: list) -> int:
        """按最宽的编号算编号列宽度（用 QFontMetrics 量，别按字数估）。"""
        return ExitsEditor.calc_tag_width(tags)

    def _make_exit_row(self, tag: str, txt: str,
                       orig_prefix: str = "", orig_line: str = "",
                       tag_w: int = None) -> QWidget:
        """见 `ui/exits_editor.py::ExitsEditor._make_row`。"""
        ed = getattr(self, "_exit_form_widget", None)
        if ed is None:
            return QWidget()
        return ed._make_row(tag, txt, orig_prefix, orig_line, tag_w)

    def _add_exit_row(self) -> None:
        ed = getattr(self, "_exit_form_widget", None)
        if ed is None:
            return
        ed.add_row()

    def _schedule_exit_rows(self) -> None:
        """排队重算出入口行高（合并同帧内的重复请求）。"""
        ed = getattr(self, "_exit_form_widget", None)
        if ed is None:
            return
        ed._schedule_relayout()

    def _relayout_exit_rows(self) -> None:
        """按**当前可用宽度**给每个出口的内容框定高（见 `ExitsEditor.relayout_rows`）。"""
        ed = getattr(self, "_exit_form_widget", None)
        if ed is not None:
            ed.relayout_rows()
            return
        for row in getattr(self, "_exit_rows", []):   # 兜底：控件被换掉时仍能用
            try:
                txt_ed = row[1]
                vw = txt_ed.viewport().width()
                if vw < 40:
                    continue
                fm = QFontMetrics(txt_ed.font())
                need = fm.boundingRect(
                    QRect(0, 0, max(20, vw - 4), 100000),
                    Qt.TextWordWrap, txt_ed.toPlainText()).height()
                txt_ed.setFixedHeight(int(max(32, need + 12)))
            except Exception:
                pass

    def _collect_exits(self) -> str:
        """把两栏拼回存储格式（**格式不变**，379 站数据不用迁移）。

        ★ 关键设计：**没动过的行原样吐回**。
          为什么不能一律"编号 + '出入口' + '：' + 内容"地重拼 —— 真实数据里有
          `6A号出入口`（多了个"号"）、`A1出口`（写的是"出口"）、
          `E出入囗`（官网错别字）、`9出入口`（连冒号都没有）这些写法。
          一律重拼就等于：**用户打开弹窗、什么都没改、点保存，
          12 行数据被悄悄改写**。所以按"有没有动过"分两条路。
        """
        ed = getattr(self, "_exit_form_widget", None)
        if ed is not None:
            return ed.text()
        # 兜底（回归测试会直接塞 `_exit_rows` 假控件进来，那时没有真控件）
        parts = []
        for tag_ed, txt_ed, orig_tag, orig_txt, orig_line in getattr(self, "_exit_rows", []):
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

    def _schedule_round_region(self, delay: int = 0) -> None:
        """排队裁圆角（同样做合并，理由见 _schedule_align）。"""
        if delay > 0:
            QTimer.singleShot(delay, self._apply_round_region)
            return
        if getattr(self, "_region_queued", False):
            return
        self._region_queued = True

        def run():
            self._region_queued = False
            self._apply_round_region()
        QTimer.singleShot(0, run)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # ★ ✕ 是浮动的（不进布局），尺寸一变必须自己重摆
        self._layout_close_btn()
        self._schedule_round_region()
        self._schedule_align()
        self._schedule_exit_rows()
        # v2.6.8：窗口变宽/变窄 ⇒ 换行位置变了 ⇒ 多行输入框的高度要重算
        af = getattr(self, "_autofit", None)
        if af is not None:
            af.sync()

    # ============================================================
    # 封面图底边 ⇄ 简介框底边 对齐（v2.4.12）
    # ============================================================
    def _align_cover_to_desc(self, _depth: int = 0, _last: tuple | None = None) -> None:
        """让封面图按钮的**底边**与「简介」输入框的底边齐平。

        为什么不用公式硬算：按钮是 `Qt.AlignVCenter` 挂在右列里，
        而**右列高度本身又受按钮高度影响**（按钮比右列高就会把右列撑高），
        两者互相耦合 —— 直接代入 `s = R - 2·extra` 会卡在不动点上。

        实测的线性关系（本机，简介框 192 高、新建模式带一行提示）：
            按钮 192 → 底边差 +10 ; 按钮 210 → +1 ; 按钮 230 → −9
        即 **Δ(底边差) ≈ −0.5 × Δ(按钮边长)**，斜率恒为 −0.5。
        于是用 `目标边长 = 当前边长 + 2 × 底边差` 一步收敛；
        若布局微扰导致还没齐，就带上次结果再迭代（最多 4 层，防死循环）。
        """
        d = getattr(self, "desc_edit", None)
        b = getattr(self, "cover_strip", None)
        if d is None or b is None:
            return
        # ★ v2.6.8：简介框现在是"高度自适应"的，而它的**宽度**又取决于封面按钮的
        #   宽度（两者挤在同一行）⇒ 封面变大 → 简介变窄 → 换行更多 → 简介变高
        #   → 又要求封面更大。两边互相追。所以每一轮对齐前都要先把简介框按
        #   **当前**宽度重新量一次，否则会一直拿旧高度去算，永远差一截
        #   （实测卡在 −7px 不动）。
        af = getattr(self, "_autofit", None)
        if af is not None:
            af.sync()
        h = d.height()
        if h < 40 or b.height() < 40:        # 还没布局出来，保持原样
            return
        # 底边差必须在**同一坐标系**里算（都换算到弹窗内）；跨容器比几何一定错
        # 约定：delta = 简介框底边 − 图片底边。
        #   delta > 0 → 图片还差一截没到底，要**加高**
        #   delta < 0 → 图片超出去了，要**减矮**
        delta = (d.mapTo(self, d.rect().bottomLeft()).y()
                 - b.mapTo(self, b.rect().bottomLeft()).y())
        if abs(delta) <= 1:
            return                           # 已经齐了（±1px 是像素取整）
        # 实测斜率：Δ(底边差) = −0.5 × Δ(边长)  ⇒  边长需要加 `2 × delta`
        target = b.width() + 2 * delta
        # 只做"防爆"夹取。
        # ★ v2.4.19：上限**必须与"正在被调整的按钮"解耦**。
        #   旧写法 `hi = header_right.height() + 60` —— header_right 的高度里
        #   本来就含这个按钮的高度，等于让上限跟着目标一起涨：一旦被扰动，
        #   边长涨 → 上限跟着涨 → 允许涨更多，是**正反馈**
        #   （历史上撑到过 650274px，Qt 直接 CreateDIBSection failed）。
        #   现在上限只跟"简介框高度"挂钩，而简介框高度由布局定死、不随按钮变。
        lo = max(80, h)
        hi = lo + 120           # 允许在简介框高度附近有限浮动（实测收敛在 +38 附近）
        target = max(lo, min(hi, target))
        target = max(24, min(target, 600))      # 再兜一道绝对上限，双保险
        if _last is not None and target == _last[0] and b.height() == _last[1]:
            return                           # 上一次就给的同一个值 → 停手，别来回抽搐
        b.setFixedSize(target, target)
        # 缩略图条尺寸变了 → 格子边长要跟着重算
        self._refresh_cover_strip()
        # 尺寸一变布局就重排，底边差可能有残留 → 再收敛一次
        if _depth < 4:
            QTimer.singleShot(
                0, lambda: self._align_cover_to_desc(_depth + 1, (target, b.height())))

    def _apply_round_region(self) -> None:
        """把窗口外形裁成圆角。

        为什么**不管有没有 parent 都要裁**：
          · 用 `setStyleSheet` 给 `QDialog` 写 `border-radius`，只对
            **Qt 自己绘制** 的窗口（`WA_TranslucentBackground` / Qt::FramelessWindow
            或某些平台的原生窗口）有效；
          · 而一个**有标题栏、由系统绘制边框的顶层窗口**，四角是系统画的直角，
            样式表的圆角只影响"窗口内容区"那条弧，**四角仍会露出直角**。
          实测：有 parent 的弹窗四角取色仍是自己的底色（= 没挖掉）。
        所以这里统一用 Win32 的 `SetWindowRgn` 把窗口外形直接裁圆，两条路径都覆盖。
        非 Windows 平台静默跳过（不影响功能，只是没有圆角）。
        """
        if sys.platform != "win32":
            return
        w, h = self.width(), self.height()
        if w <= 2 or h <= 2:
            return
        try:
            import ctypes
            import ctypes.wintypes as wt
            r = WINDOW_RADIUS

            hwnd = int(self.winId())
            user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32

            # ★ 关键：SetWindowRgn 用的是**窗口坐标（物理像素）**，
            #   而 Qt 的 width()/height() 是**逻辑像素**，高 DPI 下两者差 dpr 倍。
            #   直接拿逻辑值去裁，区域会比真实窗口小一圈 —— 表现就是
            #   **左边和下边被切掉一条**（右边/下边露出底下的窗口）。
            #   最稳的办法不是自己乘 dpr（各平台/各 DPI 感知模式口径不一），
            #   而是直接问 Win32 要窗口的真实像素尺寸。
            rect = wt.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                pw = rect.right - rect.left
                ph = rect.bottom - rect.top
            else:                                   # 拿不到就退回逻辑值
                dpr = float(self.devicePixelRatioF()) or 1.0
                pw, ph = int(round(w * dpr)), int(round(h * dpr))

            # 直径列表：椭圆宽度/高度，顺序 = 左上、右上、右下、左下
            ellipse = (r * 2, r * 2) * 4
            rgn = gdi32.CreateRoundRectRgn(0, 0, pw + 1, ph + 1, *ellipse)
            if rgn:
                user32.SetWindowRgn(hwnd, rgn, True)    # True = 让系统重绘
                # SetWindowRgn 成功后所有权归系统，不用（也不能）再 DeleteObject
        except Exception:
            pass                                  # 裁圆角失败不影响功能

    # ============================================================
    # 多图缩略图条（v2.6.79，替代单张封面图按钮）
    # ============================================================
    def _img_paths(self) -> list:
        """当前缩略图条里每个条目的**可用路径**（新选的本地路径优先）。"""
        dm = get_data_manager()
        out = []
        for e in self._img_entries:
            if e.get("src"):
                out.append(Path(e["src"]))
            else:
                p = dm.cover_path(e.get("name", ""))
                if p:
                    out.append(p)
        return out

    def _refresh_cover_strip(self) -> None:
        """按 _img_entries 重建缩略图网格（末尾带一枚 ＋ 格子）。"""
        grid = getattr(self, "cover_grid", None)
        if grid is None:
            return
        while grid.count():
            it = grid.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        # 格子边长跟外框宽度走：3 列，扣掉边距 + 两个列间距
        tile = max(48, (self.cover_strip.width() - 12 - 12) // 3)
        paths = self._img_paths()
        for i, p in enumerate(paths):
            btn = QToolButton()
            btn.setFixedSize(tile, tile)
            btn.setIconSize(QSize(tile - 10, tile - 10))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QToolButton { border: 1px solid #d5d9e0; border-radius: 6px; background: #f7f8fa; }
                QToolButton:hover { border-color: #1976d2; }
            """)
            btn.setIcon(_cached_cover_icon(p, tile - 10))
            btn.setToolTip(str(p.name))
            btn.clicked.connect(lambda _=False, pp=p: self._view_image(pp))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, idx=i: self._on_img_context_menu(pos, idx))
            grid.addWidget(btn, i // 3, i % 3, Qt.AlignCenter)
        # ＋ 添加格子
        add_btn = QToolButton()
        add_btn.setFixedSize(tile, tile)
        add_btn.setIconSize(QSize(tile - 10, tile - 10))
        add_btn.setIcon(make_add_image_icon(tile - 10))
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setStyleSheet("""
            QToolButton { border: 1px dashed #b6bcc6; border-radius: 6px; background: #fbfcfe; }
            QToolButton:hover { border-color: #1976d2; background: #f0f6ff; }
        """)
        add_btn.setToolTip("添加图片（可按住 Ctrl 多选）")
        add_btn.clicked.connect(self._on_add_images)
        grid.addWidget(add_btn, len(paths) // 3, len(paths) % 3, Qt.AlignCenter)

    def _view_image(self, path) -> None:
        from ui.image_viewer import show_image_viewer
        show_image_viewer(self, path)

    def _on_add_images(self) -> None:
        last = self._img_entries[-1].get("src", "") if self._img_entries else ""
        start = str(Path(last).parent) if last else str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(
            self, "添加图片（可多选）", start, IMAGE_FILTER)
        if not paths:
            return
        for p in paths:
            self._img_entries.append({"name": "", "src": p})
        self._refresh_cover_strip()

    def _on_img_context_menu(self, pos, idx: int) -> None:
        menu = QMenu(self)
        act_view = menu.addAction("🔍 查看大图")
        act_del = menu.addAction("✕ 移除此图")
        chosen = menu.exec(self.sender().mapToGlobal(pos) if self.sender() else None)
        if chosen is act_view:
            self._refresh_cover_strip()          # 先重建，拿到最新路径引用
            paths = self._img_paths()
            if idx < len(paths):
                self._view_image(paths[idx])
        elif chosen is act_del:
            if 0 <= idx < len(self._img_entries):
                self._img_entries.pop(idx)       # 旧文件等保存时统一清理
                self._refresh_cover_strip()

    def _commit_images(self, sid: str) -> list:
        """把多图的最终状态落实：新图拷进 covers/，被移除的旧图删掉。

        返回最终文件名列表（写进 payload["images"]；cover 同步 = 第一张）。
        """
        dm = get_data_manager()
        old_names = list(self._data.get("images") or [])
        cov = str(self._data.get("cover") or "").strip()
        if cov and cov not in old_names:
            old_names.insert(0, cov)
        final: list = []
        for e in self._img_entries:
            if e.get("src"):
                try:
                    final.append(dm.import_image(sid, e["src"]))
                except Exception as ex:
                    QMessageBox.warning(self, "图片导入失败", str(ex))
                    # 导入失败就丢掉这个条目，不打断保存
            else:
                final.append(e.get("name", ""))
        final = [n for n in final if n]
        for n in old_names:
            if n and n not in final:
                dm.remove_cover(n)
        return final

    # ============================================================
    # 表单
    # ============================================================
    @staticmethod
    def _make_stacked(label_text, editor: QWidget,
                      head_widget: QWidget = None) -> QWidget:
        """把一个「标签 + 输入框」竖着摞起来，整行宽（标签在上、输入框在下）。

        ★ v2.6.8：实现搬到了 `ui/form_rows.py::make_stacked`（右侧信息面板
          用的是同一份 —— 项目铁律：同一处改动只留一份代码，见 MEMORY §4.16）。
        ★ `head_widget`：v2.6.8 新增 —— 挂在这一行**标题右侧**的别的字段的输入框
          （「设施」的输入框现在挂在「出入口信息」这一行的右边）。
        """
        return make_stacked(label_text, editor, head_widget)

    @staticmethod
    def _make_inline_row(label_text: str, editor: QWidget) -> QWidget:
        """「文字在左、输入框占满右边」的**单行**行（v2.6.4）。

        形态：
            设施    [ 卫生间、电梯、母婴室                    ]

        ★ 标签要给**固定宽度**，不然各个字段的标签宽度不一样，
          所有输入框的左边缘就参差不齐（一列内容看着是歪的）。
        ★ v2.6.8：同样搬到了 `ui/form_rows.py`。
        """
        return make_inline_row(label_text, editor, INLINE_LABEL_W)

    # ------------------------------------------------------------
    @staticmethod
    def _make_table(fields: list, editors: list) -> QWidget:
        """**横向并排的一组字段**，全部挤在**同一行**里（v2.4.17）。

        形态（以「是否换乘站 + 开通日期」为例）::

            是否换乘站  ☑        开通日期  [ 例如：2011-06-22 或 建设中 ]

        即 4 个格子：`文字 | 控件 | 文字 | 控件`，全部 `AlignVCenter` 对齐。

        ★ v2.4.16 时这里是"每个字段各自「标签在上、控件在下」"的两行结构，
          用户随后要求"文字和输入框都在一行"，所以 v2.4.17 改成单行四列。

        为什么还要 `QGridLayout`（而不是 QHBoxLayout）：
        用网格能精确控制**每列宽度**（标签列按内容、输入框列给固定宽），
        而且跨列整行挂到 QFormLayout 里时表现稳定。
        """
        box = QWidget()
        g = QGridLayout(box)
        # ★ 关键：把布局的尺寸约束钉成 SetFixedSize —— 这样容器的自然宽度
        #   就是"各列按内容算出来的宽度之和"。不加这句时，本容器被
        #   QFormLayout 整行拉开后，多余宽度会被各列**平均瓜分**，
        #   控件会被拉到很宽、位置全乱（v2.4.16 实测踩过）。
        g.setSizeConstraint(QLayout.SetFixedSize)
        g.setContentsMargins(0, 0, 0, 0)
        # 同一个字段内「文字 ⇄ 控件」贴紧，**组与组之间**留大间距（见下面 col 推算）
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(0)

        col = 0
        for i, (fld, ed) in enumerate(zip(fields, editors)):
            if i:
                # 两组之间的间隔：用一个**固定宽度的空列**实现，
                # 比调 setHorizontalSpacing 更精确（后者会同时影响组内间距）
                g.setColumnMinimumWidth(col, PAIR_GAP)
                g.setColumnStretch(col, 0)
                col += 1

            # ① 字段文字：垂直居中，跟旁边的控件同一条基线
            g.addWidget(QLabel(fld.get("label", fld["key"])), 0, col, Qt.AlignVCenter)
            col += 1

            # ② 字段控件
            if fld.get("type") == "bool":
                # 复选框默认会横向撑满，撑满就画在格子正中 → 顶到左边去
                ed.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                g.addWidget(ed, 0, col, Qt.AlignLeft | Qt.AlignVCenter)
            else:
                # 单行输入框给个**固定宽度**（不跟着窗口拉长），整行才不会被撑散
                if isinstance(ed, QLineEdit) and not ed.maximumWidth() < 16777215:
                    ed.setFixedWidth(LINE_EDIT_WIDTH)
                g.addWidget(ed, 0, col, Qt.AlignVCenter)
            col += 1
        return box

    # ------------------------------------------------------------
    # 图标标签行：一行多组「下拉 + ⚙️ + 文字」（v2.6.69）
    # ------------------------------------------------------------
    def _make_tag_row(self, tags: list) -> QWidget:
        """图标标签行 —— 每组 = [图标按钮][方向框][手动文字输入]。

            [🛍][左][深圳湾万象城]   [✈️][左][宝安机场]

        · 图标按钮显示当前图标（空=虚线"＋"框），**点击弹出表情包式选择页**
          （按类分行：无/高铁/机场｜商场｜酒店｜豪宅，见 _pick_tag_icon）；
        · 方向框 **紧贴**按钮，框上显示当前方向字（默认左），
          点框弹菜单改「图标在文字的 上/下/左/右」；
        · 文字手动输入（可空）。
        存 `tags` 列表：[{"icon","text","pos"}]。
        ★ v2.6.76：不再固定 3 组——**每 TAG_SLOT_COUNT(3) 组一行、自动换行**
          （深圳北站 4 组标签的教训：固定 3 槽保存时会静默丢第 4 组）。
        """
        n_slots = max(TAG_SLOT_COUNT,
                      ((len(tags) + TAG_SLOT_COUNT - 1) // TAG_SLOT_COUNT)
                      * TAG_SLOT_COUNT)
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        self._tag_btns: list = []
        self._tag_icons: list = []
        self._tag_pos_btns: list = []
        self._tag_edits: list = []
        self._tag_poss: list = []

        for start in range(0, n_slots, TAG_SLOT_COUNT):
            h = QHBoxLayout()
            h.setSpacing(TAG_GROUP_GAP)
            for i in range(start, start + TAG_SLOT_COUNT):
                tag = tags[i] if i < len(tags) and isinstance(tags[i], dict) else {}
                cur_icon = str(tag.get("icon") or "")
                cur_text = str(tag.get("text") or "")
                cur_pos = str(tag.get("pos") or "left")
                if cur_pos not in TAG_POS_OPTIONS:
                    cur_pos = "left"

                b = QToolButton()
                b.setFixedSize(TAG_BTN_SIZE, TAG_BTN_SIZE)
                b.setIconSize(QSize(TAG_BTN_SIZE - 6, TAG_BTN_SIZE - 6))
                b.setToolTip("点击选择图标")
                b.clicked.connect(lambda _=False, idx=i: self._pick_tag_icon(idx))

                # v2.6.85：四个方向收进一个框——框上显示当前方向，点击弹菜单修改
                pos_btn = QToolButton()
                pos_btn.setFixedSize(TAG_POS_BOX_W, TAG_BTN_SIZE)
                pos_btn.setToolTip("图标位置（相对文字），点击修改")
                pos_btn.clicked.connect(
                    lambda _=False, k=i: self._show_tag_pos_menu(k))

                e = QLineEdit()
                e.setPlaceholderText("名称（可空）")
                e.setText(cur_text)
                e.setFixedWidth(TAG_TEXT_W)
                e.setMinimumHeight(30)

                self._tag_btns.append(b)
                self._tag_icons.append(cur_icon)
                self._tag_pos_btns.append(pos_btn)
                self._tag_edits.append(e)
                self._tag_poss.append(cur_pos)
                self._update_tag_btn(i)
                self._update_tag_pos_btns(i)

                # v2.6.87：组内套子布局（间距不叠 TAG_GROUP_GAP）——
                #   旧实际间距 13/16px（=布局 12 + 显式 1/4），60% ≈ 8/10px
                grp = QWidget()
                gh = QHBoxLayout(grp)
                gh.setContentsMargins(0, 0, 0, 0)
                gh.setSpacing(0)
                gh.addWidget(b, 0, Qt.AlignVCenter)
                gh.addSpacing(TAG_GAP_ICON_POS)       # 图标→方向框
                gh.addWidget(pos_btn, 0, Qt.AlignVCenter)
                gh.addSpacing(TAG_GAP_POS_TEXT)       # 方向框→文字框
                gh.addWidget(e, 0, Qt.AlignVCenter)
                h.addWidget(grp, 0, Qt.AlignLeft | Qt.AlignVCenter)
            h.addStretch()
            v.addLayout(h)
        return box

    def _update_tag_btn(self, idx: int) -> None:
        """图标按钮贴图：有图标贴图，无图标显示虚线"＋"。"""
        b = self._tag_btns[idx]
        ic = str(self._tag_icons[idx] or "")
        pm = icon_pixmap(ic, 48) if ic else None
        if pm is not None and not pm.isNull():
            b.setIcon(QIcon(pm))
            b.setText("")
            # v2.6.71：悬浮显示含义原文（如 "S级·顶奢奢华：…"）
            b.setToolTip(_icon_tooltip(ic))
        else:
            b.setIcon(QIcon())
            b.setText("＋" if not ic else ic)
            b.setToolTip("点击选择图标")

    def _pick_tag_icon(self, idx: int) -> None:
        """表情包式图标选择页：**按类分行**平铺图标，点一下选走。

        · v2.6.85：纯 Qt.Popup（无标题栏/无❌，点弹窗外空白即关闭）；
        · 行结构按 ICON_CATALOG 分组：第1行=无/高铁/机场，2=商场，3=酒店，4=豪宅；
        · 每个图标悬浮显示含义原文（_icon_tooltip）。
        """
        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.Popup)          # ★ 只有 Popup：无边框、点外即关
        v = QVBoxLayout(dlg)
        v.setContentsMargins(10, 10, 10, 10)
        g = QGridLayout()
        g.setSpacing(6)
        ROWS = [ICON_CATALOG[0:3], ICON_CATALOG[3:7], ICON_CATALOG[7:11],
                ICON_CATALOG[11:15]]
        for r, row in enumerate(ROWS):
            for c, (val, lab) in enumerate(row):
                b = QToolButton()
                b.setFixedSize(46, 46)
                # 每个图标悬浮显示含义原文
                b.setToolTip(_icon_tooltip(val))
                if val:
                    pm = icon_pixmap(val, 64)
                    if pm is not None and not pm.isNull():
                        b.setIcon(QIcon(pm))
                        b.setIconSize(QSize(34, 34))
                    else:
                        b.setText(lab[:2])
                else:
                    b.setText("无")
                b.clicked.connect(lambda _=False, v_=val, k=idx: self._set_tag_icon(k, v_))
                b.clicked.connect(dlg.close)
                g.addWidget(b, r, c)
        v.addLayout(g)
        pos = self._tag_btns[idx].mapToGlobal(
            self._tag_btns[idx].rect().bottomLeft())
        dlg.move(pos)
        dlg.exec()   # ★ exec() 不收位置参数（传参会 TypeError ⇒ 选图标"无效"），先 move 再 exec

    def _set_tag_icon(self, idx: int, val: str) -> None:
        self._tag_icons[idx] = str(val or "")
        self._update_tag_btn(idx)

    def _update_tag_pos_btns(self, idx: int) -> None:
        """方向框文字同步为当前方向（v2.6.85）。"""
        self._tag_pos_btns[idx].setText(
            TAG_POS_CHARS.get(self._tag_poss[idx], "左"))

    def _set_tag_pos(self, idx: int, pos: str) -> None:
        self._tag_poss[idx] = pos
        self._update_tag_pos_btns(idx)

    def _show_tag_pos_menu(self, idx: int) -> None:
        """方向框弹出「上/下/左/右」菜单（当前项打勾）。"""
        m = QMenu(self)
        for pos in TAG_POS_MENU_ORDER:
            act = m.addAction(TAG_POS_CHARS[pos])   # ★ v2.6.86：只显示 上/下/左/右
            act.setCheckable(True)
            act.setChecked(self._tag_poss[idx] == pos)
            act.triggered.connect(lambda _=False, p=pos, k=idx: self._set_tag_pos(k, p))
        m.exec(self._tag_pos_btns[idx].mapToGlobal(
            self._tag_pos_btns[idx].rect().bottomLeft()))

    def _collect_tags(self) -> list:
        """把各组拼回 `tags` 列表；图标为空的组丢弃。"""
        out = []
        for ic, e, p in zip(self._tag_icons, self._tag_edits, self._tag_poss):
            ic = str(ic or "")
            if not ic:
                continue
            out.append({"icon": ic, "text": str(e.text()).strip(), "pos": p})
        return out

    # ------------------------------------------------------------
    def _hrow_fields(self):
        """返回要**并成一行**的字段规格列表（v2.4.16）。

        数据驱动：schema 里给任一条加 `"row_with": "<另一个字段 key>"` 即可配对。
        """
        rows = []
        used = set()
        for field in EDITABLE_FIELDS:
            k = field["key"]
            if k in used or not field.get("row_with"):
                continue
            mate_key = field["row_with"]
            mate = next((f for f in EDITABLE_FIELDS if f["key"] == mate_key), None)
            if mate is None:
                continue
            # ★ 排列顺序按 **EDITABLE_FIELDS 里的先后**，不能按 [声明者, 被声明者]：
            #   `open_date` 声明 `row_with = is_transfer`，若直接 append
            #   [open_date, is_transfer] 就会把"开通日期"排到左边，
            #   而用户要的是它在"是否换乘站"**右侧**。
            order = [x["key"] for x in EDITABLE_FIELDS]
            rows.append(sorted([field, mate], key=lambda f: order.index(f["key"])))
            used.update((k, mate_key))
        return rows

    def _build_form(self):
        data = self._data
        lines = get_data_manager().all_lines()
        hrows = self._hrow_fields()
        hrow_keys = {f["key"] for row in hrows for f in row}

        # 顶部已经放过的字段，表单里不再重复出行
        # ★ v2.7.0：再把「界面隐藏字段」并进来 —— 用户要求从弹窗里删掉；
        #   数据不动（合并写入，payload 不带就保原值）。
        # ★ v2.7.4：这个集合现在只剩「设施」；「出入口信息」改走
        #   `READONLY_UI_FIELDS`（照常显示、只读、不回写），所以**不再 SKIP**。
        SKIP = ("station_name", "description", "lines") + tuple(HIDDEN_UI_FIELDS)

        # ---------------- 第一遍：把所有控件造出来 ----------------
        # ★ v2.4.16 为什么分两遍：并排行里的两个控件**必须都已经存在**才能挂。
        #   如果一边遍历 schema 一边挂，还没轮到第二个成员（开通日期在
        #   is_transfer 之后）就先遇到了并排行 → 控件是 None → 整行被跳过、
        #   字段从表单里凭空消失（实测踩过：_widgets 里没有 is_transfer /
        #   open_date，表单只剩 4 行）。
        editors: Dict[str, QWidget] = {}      # key -> 行内用的控件
        rows_v: Dict[str, QWidget] = {}       # key -> 竖排时整行的外层 widget

        for field in EDITABLE_FIELDS:
            key = field["key"]
            if key in SKIP:
                continue
            # ★ v2.7.5：`no_label` ⇒ **不画标题文字**（用户：「删除文字
            #   '出入口信息'」），与右侧面板同一份规则。
            label = None if field.get("no_label") else field.get("label", key)
            t = field.get("type", "text")
            value = data.get(key, "")
            pending = key in hrow_keys

            if t == "text":
                w = QLineEdit()
                if field.get("placeholder"):
                    w.setPlaceholderText(field["placeholder"])
                w.setText(str(value) if value is not None else "")
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    rows_v[key] = None             # None ⇒ 用 addRow(label, w)
                    rows_v[f"__w__{key}"] = w

            elif t == "multiline" and key == EXITS_KEY:
                # v2.6.3：出入口不再是"一个大文本框"，而是**每行拆成
                # [编号][内容]** 两栏（编号加粗加大、独立出去，"出入口"三字不再出现）。
                w = self._make_exits_editor(value)
                self._exit_form_widget = w
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    rows_v[key] = self._make_stacked(label, w)
                continue

            elif t == "multiline" and key == TIMETABLE_KEY:
                # v2.6.4：首末班车不再是"一坨灰色小字"，而是
                # **按日期类型分组、线路/方向/首班/末班列对齐的表格**
                # （首班蓝药丸 / 末班红药丸 + 线路官方色圆点）。
                # v2.6.7：三种日期类型合成**一个下拉菜单**，放在原来「首末班车」
                # 标签的位置，**"首末班车"这四个字删掉**。
                # 存储格式保持不变，详见 `ui/timetable_editor.py` 文件头。
                w = TimetableEditor(value)
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    # ★ v2.6.8：不再套"标签 + 输入框"的外壳 ——
                    #   日期类型下拉已经搬进**表格自己的表头行**（表头"线路"的左侧），
                    #   这一行只需要挂表格本身。
                    rows_v[key] = w
                continue

            elif t == "multiline" and field.get("same_row"):
                # v2.6.4：**输入框只有一行高**（设施内容就是顿号隔开的一串名词，
                #   实测 379 站全单行、最长 18 字，给多行框纯属浪费地方）。
                # v2.6.8：不再显示"设施"两个字 —— 输入框挂到「出入口信息」
                #   那一行的标题右侧（schema 键 `head_with`）。
                w = QLineEdit()
                w.setMinimumHeight(30)
                if field.get("placeholder"):
                    w.setPlaceholderText(field["placeholder"])
                w.setText(str(value) if value is not None else "")
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    # ★ 先按"自己占一行"备好；等下 inject_head 成功会把它摘走。
                    #   万一挂不进去（目标行不存在），字段也不会从界面上消失。
                    rows_v[key] = self._make_inline_row(label, w)
                continue

            elif t == "multiline":
                w = QPlainTextEdit()
                if field.get("placeholder"):
                    w.setPlaceholderText(field["placeholder"])
                w.setPlainText(str(value) if value is not None else "")
                # ★ v2.6.8：高度自动拉伸（文字多少都拉伸到刚好全部显示完）
                self._autofit.add(w, min_h=AUTOFIT_MIN_H)
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    rows_v[key] = self._make_stacked(label, w)

            elif t == "tags":
                # v2.6.69：图标标签行 —— 「图标」两个字删掉，
                #   一行多组「[图标下拉][⚙️][手动文字]」（见 _make_tag_row）。
                #   存 `tags` 列表 [{"icon","text","pos"}]。
                w = self._make_tag_row(list(value or []))
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    rows_v[key] = w        # 整行容器，无标签
                continue

            elif t == "choice":
                if key == "district":
                    # v2.6.68：所属区下拉已搬到顶栏（「所属线路」右侧），表单里不再出行
                    continue
                # v2.6.67：下拉选择字段。值存 currentData，
                #   显示用 label（emoji 图标也能直接显示在选项里）。
                w = QComboBox()
                for val, lab in field.get("options") or []:
                    w.addItem(lab, val)
                cur = str(value or "")
                _i = w.findData(cur)
                w.setCurrentIndex(_i if _i >= 0 else 0)
                self._widgets[key] = w
                editors[key] = w
                if not pending:
                    rows_v[key] = None             # None ⇒ 用 addRow(label, w)
                    rows_v[f"__w__{key}"] = w

            elif t == "bool":
                w = QCheckBox()
                w.setChecked(bool(value))
                self._widgets[key] = w
                editors[key] = w
                if pending:
                    pass                           # 直接挂控件本身，见 _make_table
                else:
                    container = QWidget()
                    h = QHBoxLayout(container)
                    h.setContentsMargins(0, 0, 0, 0)
                    h.addWidget(w)
                    h.addStretch()
                    rows_v[key] = container

            elif t == "lines":
                # v2.4.13：控件已在顶栏建好（self.lines_select），这里不出行
                pass

        # ---------------- 第一遍半：把 `head_with` 的字段挂进目标行的标题右侧 ----
        # v2.6.8：「设施」的输入框 → 「出入口信息」那一行的标题右边，
        #   并且**删掉"设施"两个字**（挂过去之后它不再自己占一行，也就没有标签了）。
        # ★ 顺序：必须**等所有控件都造完**再做（`facilities` 在 schema 里排在
        #   `exits` 后面，逐字段边造边挂的话这时目标行还没建出来）。
        # ★ 失败必须**退回自己占一行** —— 宁可布局不符合预期，也不能让字段消失。
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

        # ---------------- 第二遍：按 schema 顺序把行挂上去 ----------------
        # 规则：并排行在**它第一个成员**在 schema 里的位置出场。
        # （不能"竖排行挂完再把并排行追加到末尾"，那样会掉到备注后面。）
        emitted: set = set()
        for field in EDITABLE_FIELDS:
            key = field["key"]
            if key in emitted or key in SKIP or key in _injected:
                continue
            row = next((r for r in hrows if any(f["key"] == key for f in r)), None)
            if row is not None:
                emitted.update(f["key"] for f in row)
                eds = [editors.get(f["key"]) for f in row]
                if any(e is None for e in eds):
                    continue                       # 有空缺就整行放弃，别挂半截
                self.form_layout.addRow(self._make_table(row, eds))
                continue
            emitted.add(key)
            if key not in editors:
                continue
            if key in rows_v:
                box = rows_v[key]
                if box is None:                    # 单行 text 字段
                    self.form_layout.addRow(
                        field.get("label", key), rows_v[f"__w__{key}"])
                else:
                    self.form_layout.addRow(box)

    # ============================================================
    def _collect(self) -> Dict:
        out: Dict = {}
        for field in EDITABLE_FIELDS:
            key = field["key"]
            t = field.get("type", "text")
            # ★★ v2.7.4：**只读展示字段一律不回写**（当前只有「出入口信息」）。
            #   与右侧面板同一套规则：控件只读 + 这里不收 ⇒ payload 里没有这个键
            #   ⇒ `upsert_station` 合并写入保留原值，数据零风险。
            if key in READONLY_UI_FIELDS:
                continue
            w = self._widgets.get(key)
            if w is None:
                continue
            if t == "text":
                out[key] = w.text().strip()
            elif t == "multiline":
                # ★ v2.6.3 起"多行字段"的控件已经**不再是同一个类**了：
                #   · exits     → 两栏容器（`_collect_exits` 拼装）
                #   · timetable → 表格容器（`TimetableEditor.text()`）
                #   · facilities（same_row）→ 已经换成 QLineEdit
                #   一律 `w.toPlainText()` 会 AttributeError。
                #   ★ 按**控件类型**派发比按 schema 的 type 派发稳：
                #     以后再换 UI 实现，只要控件换了类，这里自动跟上。
                if isinstance(w, TimetableEditor):
                    out[key] = w.text()
                elif isinstance(w, QPlainTextEdit):
                    out[key] = w.toPlainText().strip()
                elif isinstance(w, QLineEdit):
                    out[key] = w.text().strip()
                elif key == EXITS_KEY:
                    out[key] = self._collect_exits()
            elif t == "tags":
                # v2.6.69：图标标签 = 各组 [下拉+⚙️+文字] 拼回列表
                out[key] = self._collect_tags()
            elif t == "choice":
                # v2.6.67：下拉字段的值 = currentData（存的是选项 value，不是显示文字）
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
        # ★ v2.6.6：「是否换乘站」勾选框已从表单删除（用户要求），
        #   改由「所属线路」推导。必须在这里补上 —— 不补的话 payload 里没有
        #   `is_transfer`，保存后它的值会永远停在打开弹窗那一刻的旧值：
        #   把 1 条线改成 2 条，地图上的圆点还是普通大小。
        return derive_is_transfer(out)

    def _on_save(self):
        payload = self._collect()
        if not payload.get("station_name"):
            QMessageBox.warning(self, "校验失败", "站点名称不能为空")
            return

        if self.is_new:
            # station_id 输入行已移除，新建站点统一由数据层生成 id
            sid = get_data_manager().generate_station_id(payload.get("station_name", ""))
        else:
            sid = self._station_id

        # 多图（"新建"时 id 也是这一刻才知道，所以要放在 sid 确定之后）
        #   ★ images = 最终文件名列表；cover 同步 = 第一张（旧读路径兼容）
        _imgs = self._commit_images(sid)
        payload["images"] = _imgs
        payload["cover"] = _imgs[0] if _imgs else ""

        self.save_requested.emit(sid, payload)
        self.accept()

    # ============================================================
    # 关闭时留一条面包屑（v2.4.19）
    # ============================================================
    def closeEvent(self, event):
        """弹窗关闭时记一行日志。

        配合 core/watchdog：以后万一又出现"未响应"，日志里能看到
        "最后一次打开的弹窗有没有正常关闭"，是排查的关键线索。
        """
        try:
            from core import watchdog
            watchdog.note(f"弹窗关闭 {self.windowTitle()}")
        except Exception:
            pass
        super().closeEvent(event)
