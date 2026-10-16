"""
ui/metro_render.py
========================
地铁图渲染层：把线路和站点画成矢量图形（不依赖任何底图）。

关键组件：
  - build_smooth_path(points)   把折线转成平滑曲线（Catmull-Rom → Bezier）
  - MetroLineItem               一条线路（粗色线）
  - HaloLabel                   带白色描边的站名文字（压在彩色线上也看得清）
  - StationDotItem              一个站点（白底圆点 + 线色描边 + 站名）

尺寸策略（核心）：
  所有图元的视觉尺寸都用「屏幕像素」定义，内部换算成场景坐标。
  圆点/文字在屏幕上**基本**大小恒定 —— 并且站名会随放大而适度变大
  （见 effective_font_px）：缩到最远 10px → 1:1 约 15px → 放到最大 20px。
  这样既能像深圳地铁官方图那样"缩小也看得清"，又能满足
  "放大是为了看清"的直觉。

  ★ 站名的实现细节：标签图元自己带一个 1/缩放 的缩放（label.setScale），
    于是【标签局部单位 == 屏幕像素】。字号取整的误差因此只剩 0.5px，
    且随放大单调不减 —— 见 StationDotItem.apply_view_scale 的长注释。

站名可读性策略：
  1. 全站名字体加粗，并描一圈白边（halo），压在彩色线路上依然清晰；
  2. 缩得越远，字号略微收窄（12px → 10px），腾出空间放下更多站名；
    放大则字号跟着变大（12px → 20px）；
  3. 站名可以放在圆点的右/左/上/下四个方向，由 MapView 做防重叠排版。

线路几何策略（★ 别改坏）：
  线路只由"站序 + 各站坐标"生成，所以**线必须精确穿过每一站**。
  实现上：八向布线造出来的"45°折点"可以倒圆角（好看），
  但**站点顶点一律不倒圆角**（精确过点）—— 倒圆角就是削角，会把线从
  圆点底下挪走（实测最大偏 78 场景单位 = 最大缩放下 624 屏幕px）。
  见 build_octilinear_path。
"""

from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QPointF, QRectF
# ★ `QPolygonF` 在 **QtGui** 里，不在 QtCore（写成 QtCore 会直接 ImportError）
from PySide6.QtGui import (
    QPainterPath, QPainter, QColor, QPen, QBrush, QFont, QFontMetricsF, QPixmap,
    QPolygonF, QPainterPathStroker,
)
from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsItem, QGraphicsObject, QGraphicsSimpleTextItem,
    QStyleOptionGraphicsItem, QToolTip,
)


# ★★ v2.6.43：三个「物理下限」（字号最小 4px / 线最细 3px / 圆点最小 3.4px）
#   **默认全部关掉**。
#   为什么：它们是"屏幕恒定"量，跟等比字号线宽**不是一把尺子** ⇒
#   越缩小，它们在地图里反而越"粗"，把站名顶得越来越远（实测 0.4 档净空 19
#   → 0.1 档 42，涨 2.2 倍），正是用户「缩小会远离、放大会靠近还是没修复」。
#   照片缩放**没有下限** —— 缩到 0.1 倍时字就是 3px、线就是 2.2px、点就是 1.1px。
#   小档看不清字？用右上角的「字体缩放」滑块单独放大，别拿下限去拧整体比例。
#   A/B：`METROEDITOR_PHYSICAL_MINS=1` 退回 v2.6.42 那套（回归用它做变异）。
PHYSICAL_MINS = __import__("os").environ.get(
    "METROEDITOR_PHYSICAL_MINS", "0") != "0"

# 屏幕像素尺寸常量（视觉调优参数）
SCREEN_NORMAL_R = 3.4      # 普通站半径（屏幕像素）
# ★ v2.6.30：普通站圆点的**场景**半径 = 原图直径 22 ÷ 2（同 LINE_W_SCENE=22 一个量纲）。
#   以前普通站是"屏幕恒定 3.4px"，而线宽(22×scale)、药丸(26/128×scale)都跟着地图长
#   ⇒ 越放大圆点相对越小，用户原话「怎么放大了图片，站点的圆圈还变小了？」。
NORMAL_R_SCENE = float(__import__("os").environ.get(
    "METROEDITOR_NORMAL_R_SCENE", "11.0"))
# ★ v2.6.12：用户要「换乘站的图标要比普通站点更加大和醒目」⇒ 5.2 → 7.0
#   （直径 14.0 vs 普通站 6.8，**两倍出头**）。★ 上面那段配平表是按 7.0 算的，
#   改这里必须**同步重算**弧宽/箭头/核心，否则会糊成一坨或戳出白底圆。
SCREEN_TRANSFER_R = 7.0    # 换乘站半径（v2.6.19 起仅作药丸**半宽**沿用）
# ★ v2.6.19：用户指定换乘站用「原图那种大药丸」—— 白色胶囊。
#   原图实测：普通站是 22×22 正圆；换乘站是 25×48 胶囊（机场北、岗厦等），
#   高/宽 ≈ 1.92。
# ★★ v2.6.20：用户反馈两句 ——
#     ①「你胶囊下了两条线路的排列方式有问题，原图是为了错开，而你还是把他们聚集到了一起」
#     ②「所有的都有问题，你仔细看原图胶囊的方向，横着、竖着、斜着作用都不一样的」
#   实测原图后确认：
#     · 每个换乘站的药丸**有方向**：横 13 / 竖 43 / 斜 12（45° 与 135° 各有）。
#       方向 = 该站各条线"并排走廊"的排列方向 —— 并排的线间距约 50 原图像素，
#       药丸**横跨**这几条走廊把它们串起来（例：车公庙 7/9/11 三条竖走廊
#       分别在 x 偏 −49/ +6/ +51，药丸就是横的、长 128）。
#     · 药丸长度不固定：2 条线约 50，3 条线约 78，4~5 条线 114~140（原图内部像素）。
#   这些**逐个从原图量出来**存进 data/stations.json 的 `pill` / `lanes`
#   （见 tools/measure_transfer_layout.py），渲染层照抄即可，不再用固定 25×48。
#   换算：原图内部宽 26px ↔ 屏幕 14px ⇒ 半宽 7.0 像素，长度按 长/宽 等比放大。
# ★★ v2.6.25：SCREEN_TRANSFER_RX 由 7.0 降到 3.0。
#   原因：用户原话「胶囊的左右刚好遮住线路图左和右一点，你现在完全是乱搞比例」。
#   药丸的**长轴**必须够到最外侧走廊（见 pill_half 里的 need），而短轴下限一旦偏大，
#   "长轴 = 短轴 × 比例"就会被这个下限顶起来 ⇒ 缩到 10% 视图时药丸半长 34px、
#   而两条走廊外缘只有 6px，药丸比走廊宽 5 倍 —— 就是"乱搞比例"。
#   ★ 1:1 档（缩放 0.54）完全不受影响：那时 hw = 26/2×0.54 = 7.0 > 3.0，走场景值。
#   ★ RX 为什么是 4.0 不是更小：原图换乘药丸宽 26、普通站圆点直径 22，
#     药丸只比普通站**宽一点点**（26/22 = 1.18），靠"长"来区分 2/3/4 线。
#     第一版拍脑袋写成 3.0，结果缩到小档药丸比普通站圆点(3.4)还窄 —— 换乘站反而
#     看不出来了（`_chk_label_on_line`「换乘站比普通站更大」当场抓到）。
# ★ v2.6.55 自动追踪（乙）：**拖动站点时吸到官方原图的走廊上**。
#   像磁铁 —— 只在离走廊 ≤ TRACE_SNAP_R（场景单位 == 原图像素）时才吸，
#   离得远就还是自由拖（不然站点只能待在线上，想微调都调不动）。
#   ★ 数字怎么定的：相邻站间距典型 240px、走廊半宽 11px，30px 大约是"手指一抖"
#     的量级 —— 拖到附近就啪一下归位，拖到别处不会硬拉。
# ★★ v2.6.82：默认改为**关**。点云（trace_cloud）有噪声/缺失、与官方中心线
#   偏差普遍 13~17px（文锦实测：用户拖到正确中心 (5219,5701)，松手被吸到
#   (5202,5702)，差 17px）⇒ 用户「手动无法把站点拖拽到底图正确的中心」。
#   信任红线：自动测量只作参考，定位一律手动调。要恢复吸附设环境变量
#   METROEDITOR_TRACE_SNAP=1（半径仍可用 METROEDITOR_TRACE_SNAP_R 调）。
TRACE_SNAP = os.environ.get("METROEDITOR_TRACE_SNAP", "0") == "1"
TRACE_SNAP_R = float(os.environ.get("METROEDITOR_TRACE_SNAP_R", "30.0"))

SCREEN_TRANSFER_RX = 4.0    # 换乘站药丸 半宽下限（屏幕像素）= 普通站 3.4 × 26/22
SCREEN_TRANSFER_RY = 13.4   # 换乘站药丸 半长（屏幕像素）—— **仅作无数据时的缺省**
LINE_W_SCENE = 22.0         # 线路场景线宽（原图实测，见 v2.6.21）
PILL_OVER = 3.0             # 药丸两端比最外侧走廊**外缘**多出多少（场景单位，原图实测 ≈3）
PILL_MIN_RATIO = 1.6        # 长轴至少是短轴的几倍（保证还是"胶囊"不是"圆"）
# ★★ v2.6.20 补：原图药丸除了白心，外面还有一圈**很粗的黑描边**。
#    实测（tools/_probe_pill_size.py，沿药丸短轴取样）：
#      白心 26  →  `######oWWWW…Wo######`  → 两侧各约 7px 黑边  ⇒ **外廓 41**
#    data 里的 pill.wid / pill.len 是泛洪出来的**白心**尺寸，所以：
#      画药丸的路径半径 = 白心/2 + 边缘厚/2（在描边环的中线上）
#      描边宽度         = 边缘厚（7，场景单位）
#      ⇒ 覆盖 [白心/2 , 白心/2 + 7]，白心正好 26、外廓正好 41，与原图逐像素对齐。
#    第一版漏了这 7px，药丸比原图瘦一圈（26 vs 41，差 37%），肉眼就是"没原图那么胖"。
TRANSFER_PILL_BORDER = float(__import__("os").environ.get("METROEDITOR_PILL_BORDER", "7.0"))
# ↑ 默认 7.0（原图实测）。设 METROEDITOR_PILL_BORDER=0 可关掉这圈黑边，
#   专供回归做**A/B 对照**：用来证明"某个别的判据失败"到底是这圈黑边引起的，
#   还是本来就有（与 METROEDITOR_NO_LANES 同一套路）。
SCREEN_DOT_STROKE = 1.9    # （旧）圆点描边宽 —— 屏幕像素，仅供 A/B
# ★ v2.6.43：描边也改**场景单位**（原图圆点黑边 ≈2.5 原图像素）。
#   旧写法是"屏幕上恒定 1.9px" ⇒ 缩到 0.1 档时描边比圆点本身还粗
#   （圆点直径才 2.2px、描边 1.9px）⇒ 整个点糊成一个大黑点 = 又一处"缩小变大"。
SCENE_DOT_STROKE = float(__import__("os").environ.get(
    "METROEDITOR_DOT_STROKE_SCENE", "2.5"))
DOT_STROKE_MIN_PX = 0.35   # 只防"完全画不出来"，程序能到的档位里不会触发
SCREEN_TRANSFER_STROKE = 1.6   # 换乘站白底圆的**余量**（弧画在 r − 弧宽/2 处）
SCREEN_LABEL_GAP = 4       # （旧）站名与圆点的间距（屏幕像素）—— 仅供 A/B 对照
# ★ v2.6.42：站名与圆点/线路之间的**呼吸量**，改成**场景单位**（原图像素系）。
#   从此"字离线的距离 : 线的粗细"在任何缩放档都是同一个比例（= 照片缩放）。
LABEL_GAP_SCENE = float(__import__("os").environ.get(
    "METROEDITOR_LABEL_GAP", "8.0"))
# ★★ v2.6.21：站名还必须**让开线宽**（场景单位）。
#   原图实测（tools/_probe_label_clearance.py，量站名文字边缘到线边缘的净空）：
#       最小 9 / 中位 28 / 最大 117 场景单位
#   也就是站名到线**中心**至少 11(线宽一半) + 9 = 20 场景单位。
#   ★ 为什么非加不可：我们的圆点半径只有 3.4 屏幕px，**比线宽一半(11)还小**，
#     站名按"圆点半径 + 间距"摆 ⇒ 近边直接落在线里面、被线穿过。
#     线宽改成"跟地图"之后回归 `_chk_label_on_line` 立刻抓到（缩放 1.0 严重压线超标）。
LABEL_LINE_CLEARANCE = float(__import__("os").environ.get("METROEDITOR_LABEL_CLEARANCE", "9.0"))
# ★ v2.6.30：站名与圆点之间的**呼吸量**（屏幕像素）。
#   上面那条 9.0 是原图像素（= 场景单位），只能用在"场景"那一侧；
#   站名离圆点该留多少，在屏幕上必须是恒定的，不然越放大字越远。
LABEL_CLEAR_PX = float(__import__("os").environ.get("METROEDITOR_LABEL_CLEAR_PX", "4.0"))
# ↑ 同上，支持设 0 关掉这条净空，供回归 A/B。

# ★ v2.6.26：拐弯弧半径**从原图量出来**（tools/measure_curve_radius.py：
#   取该线颜色的中心线、最小二乘拟合圆）。实测 **115 ~ 223，中位 ≈150**。
#   旧值 170 是当初拍脑袋定的，跟原图差 13%。
#   A/B：`METROEDITOR_FILLET_R=170` 可退回旧值。
FILLET_RADIUS = float(__import__("os").environ.get("METROEDITOR_FILLET_R", "150.0"))

# ---------------- 换乘站专属图标（v2.6.9 双环 → v2.6.11 旋转箭头环）----------------
# 用户 v2.6.9：「换乘站在交汇处用专属图标显示」⇒ 当时做成「◎」双环，
# 用户 v2.6.11 反馈：**不喜欢，要换成和悬浮提示里那个 🔄 类似的旋转图标**。
#   （悬浮提示里换乘站名前面就是 🔄，见 `ui/tooltip.py::show_for`）
# 所以现在画的是**两条带箭头的弧首尾相接围成环**（通行做法里的"换乘/转乘"标）：
#   白底圆 → 两段深色弧（各 132°，缺口留在左右两侧）→ 两个箭头同向
#   → 中心线路色实点
# ★★ 尺寸是按"白底圆 7.0px 半径"配平的，**改动前先算一遍**（v2.6.9 就栽在
#    "内白带只剩 0.39px，1:1 糊成一坨"；v2.6.12 用户要「比普通站更大更醒目」，
#    半径 5.2 → **7.0**，普通站是 3.4 ⇒ 直径 14.0 vs 6.8，**两倍出头**）：
#     白底圆        r = 7.0px
#     弧线中心半径  ring_r = r − 弧宽/2 = 7.0 − 1.0 = 6.0px
#     弧宽          2.0px ⇒ 弧占 5.00 … 7.00px（外缘正好贴白底圆边缘）
#     箭头          角向跨度 34°（箭尖探进缺口 26°、底边退 8°），径向半宽 1.55px
#     箭头径向中心  ring_r − 0.5 = 5.5px ⇒ 径向范围 3.95 … 7.05px（不戳出圆外）
#     中心实点      r = 7.0×0.26 = 1.82px（离弧内缘还有 3.18px 白）
#   ⇒ 内部留白 = 5.00 − 1.82 = **3.18px**，不会糊。
TRANSFER_RING_COLOR = "#243244"
SCREEN_TRANSFER_ARC = 2.0        # 弧线宽（屏幕像素）
SCREEN_TRANSFER_ARROW_W = 1.55   # 箭头的**径向半宽**（屏幕像素，比弧半宽 1.0 大）
TRANSFER_ARROW_RING_OFF = -0.5   # 箭头的径向中心相对弧中心线**往里**偏（别戳出白底圆）
TRANSFER_ARROW_TIP_LEAD = 26     # 箭尖比弧末端再往前多少度（★ 要明显探进缺口才能被验到）
TRANSFER_ARROW_BACK = 8          # 箭头底边比弧末端往回多少度
TRANSFER_ARC_SPAN = 132          # 每段弧跨度（度）—— 留 48° 缺口给箭头/断裂感
TRANSFER_ARC_START = 24          # 第一段起始角（度，0°=3 点钟，逆时针为正）
TRANSFER_CORE_RATIO = 0.26       # 中心线路色实点半径 / 外圈半径
# （v2.6.9 的 `SCREEN_TRANSFER_RING` / `TRANSFER_RING_RATIO` 已随双环画法一起删掉）


def transfer_arrow_points(ring_r: float, end_deg: float,
                          w: float = SCREEN_TRANSFER_ARROW_W,
                          off: float = TRANSFER_ARROW_RING_OFF):
    """箭头三角形的三个顶点（**屏幕像素**量纲，控件坐标 y 向下为正）。

    ★★ 顶点必须沿**弧**布置（箭尖在 `end+lead`、底边在 `end−back`，
       两者都落在半径 `ring_r + off` 上），**不能**沿切线往后退：
       沿切线退 L 之后底边到圆心的距离是 `sqrt(ring_r² + L²)`
       —— L=3 时就是 **5.37px > 外圈 5.2px**，整个箭头会飞到圆外面去
       （v2.6.11 第一版就是这么画的，实测采样点取到的是**背景色** #f7f9fb）。
    ★★ 箭尖必须在**角度**上明显探进缺口（`TIP_LEAD=26°`）：
       弧带本身只有 1.5px 宽，在弧带里取样分不清"这是弧还是箭头"；
       缺口里除了箭头**不可能有别的深色**（弧的 RoundCap 只往里伸 ~9.6°），
       所以回归脚本是在缺口扇区里**数深色像素**来验"有没有箭头"。
    ★ `off` 把箭头整体往里挪一点：径向最外 `ring_r+off+w = 5.25px`
      ≈ 白底圆 5.20px，不会戳到圆外面变成一根刺。
    """
    rc = ring_r + off
    tip_a = math.radians(end_deg + TRANSFER_ARROW_TIP_LEAD)
    base_a = math.radians(end_deg - TRANSFER_ARROW_BACK)

    def pol(r, a):
        return (r * math.cos(a), -r * math.sin(a))   # ★ y 向下 ⇒ 取负

    return [pol(rc, tip_a),
            pol(rc + w, base_a),
            pol(rc - w, base_a)]

# ---------------- 线路线宽（v2.6.21 改成"跟地图"）----------------
# ★★ 为什么必须改：原图（8000×8000）的线宽是**恒定 ≈22 像素**（= 22 场景单位），
#    而我们原来是"屏幕上恒定 4.6 像素" ⇒ 场景线宽 = 4.6/缩放，**跟着缩放跑**：
#       · 放大到 1:1（与原图同尺寸）时只有 4.5 场景单位 ⇒ 比原图**细 5 倍**
#         （tools/_probe_line_width.py 在 6 个换乘站实测：原图 20~25，我们 3~6）；
#       · 默认 10% 视图时却是 46 场景单位 ⇒ 反而比原图**粗一倍**。
#    两个方向都不对 —— 因为线宽本来就该是地图自身的属性，不是屏幕的属性。
# ★ 做法：**场景恒定 22 + 屏幕下限 3px**（缩到整图时线不能细到看不见）。
# ★★ 改了这里必须同时改"站名避让线路"的墨迹宽度：那边原来也硬用 SCREEN_LINE_W，
#    线变粗后避让会算少 ⇒ 站名压到线上。统一走 `line_screen_width()`。
SCENE_LINE_W = float(__import__("os").environ.get("METROEDITOR_LINE_W", "22.0"))
SCREEN_LINE_MIN = float(__import__("os").environ.get("METROEDITOR_LINE_MIN",
                                                    "3.0" if PHYSICAL_MINS else "0.5"))
# ★ v2.6.43：下限 3.0px 在 0.136 档以下触发 ⇒ 线在地图里变粗（0.1 档 30 场景 vs 22）
#   ⇒ 站名为了让开线被推远。改成 0.5 后，程序能到的最小档 0.10 都还是纯等比 22。
# ↑ 这两个支持环境变量覆盖，**专供回归做 A/B 对照**（同 METROEDITOR_NO_LANES 套路）：
#   设 `METROEDITOR_LINE_W=0 METROEDITOR_LINE_MIN=4.6` 就精确复现 v2.6.20 之前的
#   "屏幕恒定 4.6px" 老行为，用来证明某个判据失败到底是这轮改线宽引起的、还是本来就有。
SCREEN_LINE_W = 4.6        # 旧常量：**仅**在拿不到缩放信息的地方兜底用


def line_scene_width(scale: float) -> float:
    """当前缩放下线的**场景**宽度（画路径用）。"""
    s = max(scale, 0.01)
    return max(SCENE_LINE_W, SCREEN_LINE_MIN / s)


def line_screen_width(scale: float) -> float:
    """当前缩放下线在**屏幕上**占多少像素（站名避让按它算墨迹半宽）。"""
    return line_scene_width(scale) * max(scale, 0.01)


def normal_dot_screen_r(scale: float) -> float:
    """普通站圆点的**屏幕**半径（v2.6.30 起跟场景，v2.6.31 抽成公用函数）。

    ★ 之所以要能"按任意缩放现算"：缩放动画的合成帧是**屏幕坐标**画的，
      而站点图元在动画期间 `_view_scale` 是冻结的 —— 合成帧必须自己按
      当前虚拟缩放算尺寸，否则圆点会在松手那一步跳一下（见 render_sprite 注释）。
    A/B：METROEDITOR_NORMAL_R_SCENE=0 退回 v2.6.29 的屏幕恒定 3.4。
    """
    s = max(scale, 0.01)
    if NORMAL_R_SCENE <= 0.0:
        return SCREEN_NORMAL_R
    r = NORMAL_R_SCENE * s
    # ★ v2.6.43：默认**纯等比**（照片缩放）。旧的三档（软下限 → 硬下限 → 屏幕恒定）
    #   全都是"屏幕像素"量，会在小档把圆点在地图里撑大，进而把站名顶远。
    if PHYSICAL_MINS or os.environ.get("METROEDITOR_PILL_HARD_MIN", "0") == "1":
        return (r ** 4 + SCREEN_NORMAL_R ** 4) ** 0.25
    return r


# 站名字号：按缩放级别自适应
SCREEN_FONT_PX = 12.0       # 基准屏幕字号（缩放 == FONT_GROW_AT 时）
SCREEN_FONT_MIN_PX = 10.0   # 缩到最远时的最小字号（保底可读）
SCREEN_FONT_MAX_PX = 20.0   # 放到最大时的字号上限（再大只会挤掉别的站名）
FONT_MIN_AT = 0.08          # 收到最小字号的缩放级别
FONT_GROW_AT = 0.30         # ★ 字号分界：≤ 它收窄（10→12px）；> 它随放大变大（12→20px）
FONT_MAX_AT = 8.0           # 放大到此缩放时字号到达上限（= MapView._zoom_max）

LABEL_HALO_PX = 2.2         # 站名白色描边宽度（屏幕像素）
# ★ v2.6.31：站名 sprite 四周留的余量（白色描边会画出 boundingRect 外）
LABEL_SPRITE_PAD = 4.0

# ★ 判定"松手时到底有没有真的拖动过站点"的位移下限（场景单位）。
#   0.05 场景单位在最大缩放 8x 下只有 0.4 屏幕px —— 远小于任何有意的拖动，
#   又足以滤掉鼠标按下时的手抖。没超过它就当"只是点了一下"，不落盘、不重建线路。
STATION_MOVE_EPS = 0.05
# ★★ v2.6.91：拖站"单步跳变否决"阈值（场景单位）。
#   病根（用户：「轻微拖动被错误放大拖动距离」，布吉曾被拖到 (28.9, 5.1)）：
#   站点拖动走 Qt 内建 ItemIsMovable，鼠标位移按**视图真实变换**映射成场景
#   位移 —— 一旦真实变换与屏幕显示脱节（缩放手势期间真实变换被驱动、屏幕
#   显示的是合成快照），一次 mouseMove 就能把图元甩到几百上千场景单位外。
#   人手一次 mouseMove 事件（~16ms）在最高缩放下也只有几个场景单位，
#   200 是它的 30 倍以上余量 ⇒ 正常拖动永远碰不到，故障跳变必被拦下。
DRAG_JUMP_LIMIT = float(os.environ.get("METROEDITOR_DRAG_JUMP_LIMIT", "200.0"))

# 站名可以摆放的八个方向（由 MapView 按顺序尝试）
#   ★ 前四个是"正方向"（优先用，观感最规整）；后四个是**斜角**兜底 ——
#     密集区域里正方向常常全被占满，多个斜角位能不放宽重叠也塞下更多站名
#     （实测缩到最小时：只靠四向能放 102 个，加斜角后多出几十个，且一个都不重叠）。
LABEL_SIDES = ("right", "left", "top", "bottom", "rt", "lt", "rb", "lb")

# ★ v2.6.61：描线（traced）的边要不要也做八向化（默认要）。见 octilinear_waypoints_tagged。
OCTI_TRACE = os.environ.get("METROEDITOR_TRACE_OCTI", "1") != "0"
LABEL_SIDES_CARDINAL = ("right", "left", "top", "bottom")


# ★ 只是**安全阀**（防字号异常时让出天际），不是日常生效的阈值 ——
#   真正管"小档别让位"的是 map_view.LABEL_RING_MIN_SCALE（0.28）：
#   那里站距 ≈70 屏幕px > 一个框宽 53px，让一圈还落在自己站上。
LABEL_RING_MAX_PX = 60.0    # （旧）外推封顶（屏幕像素）—— 仅供 A/B 对照
# ★ v2.6.42：外推封顶改**场景单位**（数值不变 ⇒ 1:1 档观感不变，缩放时跟图走）
LABEL_RING_MAX_SCENE = float(__import__("os").environ.get(
    "METROEDITOR_RING_MAX", "60.0"))
# ★ v2.6.27：外推量还要随缩放**收缩** —— 站距是 LABEL_RING_SPAN 这么宽（场景单位），
#   小档时站距在屏幕上只有几十 px，若还按"一个框宽"让位就会骑到隔壁站头上。
#   于是"让位距离 = 站距的一半"随缩放线性变小，跨阈值时不会出现站名数突然掉几个。
LABEL_RING_SPAN = 110.0     # ≈ 半个站距（场景单位）


def split_label_ring(side: str) -> tuple:
    """把带"圈数"的方向拆开：'right2' → ('right', 2)，'lb' → ('lb', 0)。

    ★ v2.6.26：站名原来只有 8 个候选位，八个方向**全压线**时就只能认了
      （用户原话「字体限制不允许显示在线路上」）。加上"往外让 1~2 圈"之后，
      候选位变成 8×3 = 24 个 —— 排版器有地方可躲，压线率才能真降下来。
      （跟米数标签的 LINK_LABEL_SIDES 是同一个套路。）
    """
    s = side or "right"
    i = len(s)
    while i > 0 and s[i - 1].isdigit():
        i -= 1
    if 0 < i < len(s):
        return s[:i], int(s[i:])
    return s, 0


def effective_font_px(view_scale: float) -> float:
    """根据当前缩放算站名的**屏幕**字号。

    用户报告：「放大后反而文字还变小了」。旧实现是
        if s >= 0.30: return 12.0        # 只要不缩小，就恒定 12px
    于是放大 100 倍（0.08→8.0）字号也只从 10px 走到 12px，**基本不变**；
    而且后面把它换算成整数场景字号（round(12/s)）再乘回缩放，
    实际呈现变成"锯齿"：实测 scale 4.5→5.0 时字号从 13.5px **掉到** 10.0px
    （−26%），这就是"放大反而变小"的字面来源。

    现在改成三段连续、**单调递增**：
        s <= 0.08           → 10px（保底）
        0.08 < s < 0.30     → 10px 线性升到 12px
        0.30 <= s <= 8.0    → 12px 按「缩放翻倍就加一档」等比升到 20px（对数线性）
        s > 8.0             → 20px（封顶）

    取对数线性（而不是线性）的理由：缩放 0.3→8 是 26.7 倍，线性放大到 20px
    在 1:1 时已经 30px、1.6 倍时 50px，站名会互相挤到几乎全被隐藏；
    按"翻倍"走则 1:1 是 14.9px、1.6 倍 16.1px、3 倍 17.6px —— 看得出在变大，
    又不至于把画面撑爆。上限 20px 已足够看清，再大只会挤掉别的站名。
    """
    if FONT_PROPORTIONAL:
        return proportional_font_px(view_scale)
    s = max(view_scale, 1e-4)
    if s <= FONT_MIN_AT:
        return SCREEN_FONT_MIN_PX
    if s < FONT_GROW_AT:
        t = (s - FONT_MIN_AT) / max(FONT_GROW_AT - FONT_MIN_AT, 1e-6)
        return SCREEN_FONT_MIN_PX + (SCREEN_FONT_PX - SCREEN_FONT_MIN_PX) * t
    if s <= FONT_GROW_AT + 1e-9:
        return SCREEN_FONT_PX
    lo = math.log(FONT_GROW_AT)
    hi = math.log(max(FONT_MAX_AT, FONT_GROW_AT * 1.0001))
    t = (math.log(s) - lo) / max(hi - lo, 1e-6)
    t = min(max(t, 0.0), 1.0)
    return SCREEN_FONT_PX + (SCREEN_FONT_MAX_PX - SCREEN_FONT_PX) * t


# ★★ v2.6.38：站名**跟图等比**（用户：「缩放文字并不会像图片缩放那样等比例」）
#   上面那套"三段式"本质是让字**尽量不随缩放变**（0.08→10px、8.0→20px，
#   缩放 100 倍字号只涨 1 倍）⇒ 图在放大、字几乎不动 = 一眼就看出"不是一张图"。
#   现在改成真正的等比：**场景字号恒定**（= 原图里量出来的字高），
#   屏幕字号 = 场景字号 × 缩放 —— 和图上的线宽(22 场景单位)、圆点(11)同一把尺子。
SCENE_FONT_PX = float(__import__("os").environ.get(
    "METROEDITOR_SCENE_FONT", "30.0"))
# 原图实测（`data/ocr_labels.json` 里 1094 个站名框）：字框高**中位 34**、
# 主峰落在 25~35 ⇒ 取 30 场景单位（OCR 框比字本身略大一圈）。
FONT_HARD_MIN_PX = float(__import__("os").environ.get(
    "METROEDITOR_FONT_MIN", "4.0" if PHYSICAL_MINS else "1.0"))
# ★ v2.6.43：下限默认 1.0px（= 实际不夹），只在"完全画不出来"时才兜底。
#   旧值 4.0 会在 0.13 档以下把字在地图里放大 33%（4/0.1 = 40 场景 vs 30）
#   ⇒ 相对地图字变大、被排版器藏掉，看着就是"缩小后字跑了/没了"。
FONT_HARD_MAX_PX = float(__import__("os").environ.get(
    "METROEDITOR_FONT_MAX", "96.0" if PHYSICAL_MINS else "400.0"))
# ★ 上限同理：旧值 96 在 3.2 档以上触发 ⇒ 字在地图里反而变小（96/4 = 24 < 30）
#   ⇒ 用户「放大会靠近」。放到 400 之后 8.0 档（最大缩放）都不触发。
FONT_PROPORTIONAL = __import__("os").environ.get(
    "METROEDITOR_FONT_PROPORTIONAL", "1") != "0"

# ★★ v2.6.54：站名框的**场景宽度**必须跨倍率恒定，否则"调好的位置换倍率就错位"。
#   病根（实测，tools/_probe_label_across_zoom.py）：
#     Qt 的字形在**小字号**下"每字号占多少像素"会变胖（hinting 非线性）——
#     "新安" 在 3px 字号下每字号占 3.33px，在 240px 下只占 2.15px，差 **55%**。
#     于是字框的【场景】宽度从 100（0.115 档）掉到 64.65（8 档），
#     半个框宽的差正是站名中心相对圆点漂的 17.67 场景单位
#     （换乘站"宝安中心"字更长 ⇒ 漂 54.72，更明显）。
#   修法：不再假设"字宽 ∝ 字号"，改按**参考字号**量出这个站名的"每像素字宽"
#     当尺子，反推出标签该缩多少 ⇒ 场景宽度 = 尺子 × 场景字号 = 恒定。
LABEL_BOX_LOCK = __import__("os").environ.get(
    "METROEDITOR_LABEL_BOX_LOCK", "1") != "0"
# 参考字号：取中偏大的一档（64px）。太小会踩到 hinting、太大没必要。
LABEL_REF_PX = 64.0
_ref_ratio_cache = {}


def ref_text_width_per_px(text: str) -> float:
    """站名在**参考字号**下的"每像素字宽"（纯文字，不含描边）。

    ★ 用 QFontMetrics 离线量，而不是拿当前档的 `label.boundingRect()` 反推：
      程序打开时往往就停在小档（自动适配全图 0.115 ⇒ 字号 3px），
      拿那一刻的度量当尺子，等于把 hinting 的误差**固定**成了标准。
    """
    if not text:
        return 0.0
    r = _ref_ratio_cache.get(text)
    if r is not None:
        return r
    try:
        f = QFont("Microsoft YaHei")
        f.setPixelSize(int(LABEL_REF_PX))
        f.setBold(True)
        r = QFontMetricsF(f).horizontalAdvance(text) / LABEL_REF_PX
    except Exception:
        r = 0.0
    _ref_ratio_cache[text] = r
    return r


_adv_cache = {}


def text_advance_at(text: str, px: int) -> float:
    """站名在**指定像素字号**下的文字宽度（局部单位 = 屏幕像素），带缓存。

    ★ 不用 `label.boundingRect()`：它是图元自己的缓存，字号刚换的那一帧
      拿到的还是**上一档**的值（实测小档会因此算错到只剩 1/4），
      而且它还把描边(halo)算进去了 —— 描边是屏幕恒定的，不该进"字宽"。
    """
    if not text or px <= 0:
        return 0.0
    k = (text, px)
    v = _adv_cache.get(k)
    if v is not None:
        return v
    try:
        f = QFont("Microsoft YaHei")
        f.setPixelSize(int(px))
        f.setBold(True)
        v = QFontMetricsF(f).horizontalAdvance(text)
    except Exception:
        v = 0.0
    _adv_cache[k] = v
    return v

# ★ v2.6.39：手动拖出来的偏移，对"被外推(ring>0)"的站名**也要生效**。
#   默认开；设 0 就退回"只有贴着圆点的站名能拖"的旧行为（回归 K2 用它做变异）。
LABEL_OFF_ALL_RINGS = __import__("os").environ.get(
    "METROEDITOR_LABEL_OFF_ALL_RINGS", "1") != "0"

# ★ v2.6.40：手动偏移用**场景单位**（跟等比站名同一把尺子）。
#   设 0 退回"屏幕像素"的旧语义（回归 L3 用它做变异）—— 那时缩放会让字
#   相对地图跑掉：缩小时被推远、放大时贴回圆点压到线上。
LABEL_OFF_SCENE = __import__("os").environ.get(
    "METROEDITOR_LABEL_OFF_SCENE", "1") != "0"


def proportional_font_px(view_scale: float) -> float:
    """等比字号（v2.6.38）：屏幕字号 = 原图字高 × 缩放，跟线宽/圆点同一把尺子。"""
    s = max(view_scale, 1e-4)
    return min(max(SCENE_FONT_PX * s, FONT_HARD_MIN_PX), FONT_HARD_MAX_PX)


OCTI_TOL = 0.16        # 偏离横/竖/45° 多少比例以内，就当它已经对齐（避免小抖动）
OCTI_TOL_PX = 26.0     # 偏差绝对值小于这么多像素，也直接连（原图站点本来就对齐）


def octilinear_waypoints_tagged(points: List[QPointF],
                                elbows: Optional[List[str]] = None
                                ) -> List[Tuple[QPointF, bool]]:
    """
    把"站点直连"展开成八向(octilinear)折线：
      横 / 竖 / 45°斜线 —— 这就是地铁示意图的画法。

    做法：两站之间若既不同横、也不同竖、也不是 45°，就先用一段 45° 斜线
    走到"横竖对齐"的位置，再走直线过去。这样每一折都是 45° 或 90°。

    ★★ v2.6.24：**45° 斜线到底放在哪一头，是照原图逐段量出来的**。
      用户原话「你很多的弯曲方向和原图都是相反的」。
      两站 a→b 且需要折点时有且只有两种合法画法（总长一样、形状镜像）：
          "a" = a --45°斜线(m 长)--> 再直线到 b      （原来写死的画法）
          "b" = a --直线--> 再 45°斜线(m 长) 到 b
      实测原图 121 段里：66 段是 "b"、53 段是 "a"、**0 段分不出来**
      （`tools/measure_elbow_side.py`：拿该线颜色的距离场给两条候选打分，
        典型的 b 段「a 端平均离色 154px、b 端 33px」，差别极其明显）。
      `elbows[i]` 描述的是 `points[i-1] → points[i]` 这一段；缺省/None = "a"。

    容差很关键：我们的站点坐标是从原图量出来的，一条直线上相邻两站本来
    应该完全对齐，但会有十几像素的测量误差。如果不设容差，每段都会多出
    一个肉眼可见的小折角，线看起来就毛躁。

    ★ 返回 [(点, 是否站点)]，供 build_rounded_polyline 区别对待：
      「站点」上必须精确过点（不许倒圆角），「45°折点」是造出来的，
      只负责好看，可以随便倒圆角。见 build_octilinear_path 的注释。
    """
    out: List[Tuple[QPointF, bool]] = [(points[0], True)]
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        dx = b.x() - a.x()
        dy = b.y() - a.y()
        adx, ady = abs(dx), abs(dy)
        big = max(adx, ady)
        if big < 1e-6:
            continue
        # 已经接近横 / 竖 / 45°，直接连
        if adx < 1e-6 or ady < 1e-6:
            out.append((b, True))
            continue
        if min(adx, ady) < OCTI_TOL_PX:
            out.append((b, True))
            continue
        if abs(adx - ady) <= big * OCTI_TOL:
            out.append((b, True))
            continue
        m = min(adx, ady)
        sx = 1.0 if dx > 0 else -1.0
        sy = 1.0 if dy > 0 else -1.0
        side = (elbows[i] if elbows is not None and i < len(elbows) else "a") or "a"
        # ★ v2.6.53：这一段被用户设成了**弧**（右键菜单的凸弧/凹弧）⇒ 采样点直接连，
        #   **不做八向化** —— 否则 10 个采样点会被各自拆成"横+45°+竖"，弧变成锯齿。
        if side == "arc":
            out.append((b, True))
            continue
        # ★ v2.6.55：自动描线的**中间点** —— 直接连，不八向化，且**不是站点**
        #   （False ⇒ 允许倒圆角，把原图像素噪声磨平）。末端的站点用 "traceS"。
        # ★★ v2.6.61：改成**也八向化**。用户原话「现在的线路是凹凸不平的」——
        #   描线贴的是官方位图的像素中心线，而位图在拐弯处是圆角 + 抗锯齿 ⇒
        #   中心线拐出来的角度是**任意的**（实测多出 41 个 25~45°、32 个 10~25°
        #   的"不大不小的折角"），看着就不规整。地铁图的规矩是横/竖/45°，
        #   官方图也是这么画的 ⇒ 描线边照规矩八向化之后反而更像官方。
        #   实测：不八向化 转角 670（其中 126 个是 10~45° 的任意角）；
        #         八向化后 这类任意角明显减少，≥45° 的规整折角增多。
        #   A/B：METROEDITOR_TRACE_OCTI=0 退回 v2.6.60 的"描线边直接连"。
        if side == "trace" and not OCTI_TRACE:
            out.append((b, False))
            continue
        if side == "traceS" and not OCTI_TRACE:
            out.append((b, True))
            continue
        # ★ v2.6.63：这一段官方原图画的是**平滑的弧**（离线判过：原样比八向化
        #   更贴官方像素，见 tools/fix_octi_twist.py）⇒ 永远不许八向化 ——
        #   八向化会把弧切成"45°斜线 + 一小段竖线"，再叠上圆角倒角，屏幕上看
        #   就是个扭曲的月牙（用户：「很多地方都有奇怪的扭曲」）。
        if side in ("traceN", "traceNS"):
            out.append((b, side == "traceNS"))
            continue
        if side == "b":
            # ★ 斜线贴 b 端：先直线走到 b 的"反方向 m 处"，再 45° 进站
            out.append((QPointF(b.x() - sx * m, b.y() - sy * m), False))
        else:
            out.append((QPointF(a.x() + sx * m, a.y() + sy * m), False))   # 45° 斜线终点
        out.append((b, True))
    return out


def _octilinear_waypoints(points: List[QPointF]) -> List[QPointF]:
    """只要点位、不要标签的旧接口（保留给外部脚本用）。"""
    return [p for p, _ in octilinear_waypoints_tagged(points)]


def build_octilinear_path(points: List[QPointF], radius: float = FILLET_RADIUS,
                          elbows: Optional[List[str]] = None) -> QPainterPath:
    """八向布线 + 圆角。地铁线路图的标准画法（横/竖/45°）。

    `elbows`：每段 45° 斜线贴哪一头（"a"/"b"），见 `octilinear_waypoints_tagged`。

    ★★ v2.6.26：**站点处也倒圆角**，靠"把控制点往外挪"让弧正好从站点身上过。

       背景（v2.6.20 的旧结论，现在被推翻）：当时为了保证「站点必须落在线上」，
       站点一律走尖角。代价就是用户这次的原话 —— **「线路很多地方不够圆润」**：
       折线的每个站点拐点都是硬邦邦的尖角，而原图那里是一道弧。

       为什么"倒圆角"和"站点在线上"现在能兼得：
         倒角弧会把拐角"削掉"，弧顶离拐点 P 差 r·sin(θ/2)/2（θ = 转角，
         二次贝塞尔 t=0.5 处的精确值）。那就**把控制点 P 沿"外侧"平移这么多**，
         弧顶正好落回 P —— 站点仍精确在线上，但线路在那里是圆的。
       ★ 方向不能搞反：弧顶偏向转弯的**内侧**，所以控制点要往**外侧**（−(u2−u1)）挪。
       ★ 只有"外侧"这一段被撑出去，前后两段直线的方向完全不变，
         所以站序、八向、肘形方向、elbow_sides 表全都不受影响。
    """
    if len(points) < 2:
        return build_rounded_polyline(points, radius)
    tagged = octilinear_waypoints_tagged(points, elbows)
    return build_rounded_polyline(
        [p for p, _ in tagged],
        radius,
        station=[is_station for _, is_station in tagged],
    )


def build_rounded_polyline(points: List[QPointF], radius: float = 110.0,
                           no_fillet: Optional[List[bool]] = None,
                           station: Optional[List[bool]] = None) -> QPainterPath:
    """
    圆角折线：相邻站点之间走直线，只有拐点处倒一个圆角。

    这才是地铁线路图该有的样子 —— 用 Catmull-Rom 样条去"穿过"每个站点
    会产生多余的 S 形弯曲和过冲，线路看起来就"飘"、就"乱"。

    station: 与 points 等长的布尔列表，True = 该顶点是**站点**
             ⇒ 仍然倒圆角，但把控制点外移 `r·sin(θ/2)/2`，使弧正好过该点
             （见 build_octilinear_path 的说明）。
    no_fillet: 旧参数（True = 走尖角精确过点），保留仅为兼容，新调用点别用。
    """
    path = QPainterPath()
    n = len(points)
    if n == 0:
        return path
    path.moveTo(points[0])
    if n == 1:
        return path
    if n == 2:
        path.lineTo(points[1])
        return path
    sit_on_curve = os.environ.get("METROEDITOR_NO_STATION_CURVE", "0") != "1"

    for i in range(1, n - 1):
        p0, p1, p2 = points[i - 1], points[i], points[i + 1]
        v1 = p1 - p0
        v2 = p2 - p1
        l1 = (v1.x() ** 2 + v1.y() ** 2) ** 0.5
        l2 = (v2.x() ** 2 + v2.y() ** 2) ** 0.5
        if l1 < 1e-6 or l2 < 1e-6:
            continue
        u1x, u1y = v1.x() / l1, v1.y() / l1
        u2x, u2y = v2.x() / l2, v2.y() / l2
        cosv = max(-1.0, min(1.0, u1x * u2x + u1y * u2y))
        turn = math.acos(cosv)                     # 转角（弧度）
        r = min(radius, l1 * 0.5, l2 * 0.5)
        if r < 1e-6 or turn < 0.14:                # < 8° 基本是直的，别折腾
            path.lineTo(p1)
            continue
        is_station = bool(station is not None and i < len(station) and station[i])
        if not sit_on_curve and (is_station or
                                 (no_fillet is not None and i < len(no_fillet)
                                  and no_fillet[i])):
            path.lineTo(p1)        # A/B：退回 v2.6.25 的"站点走尖角"
            continue
        cx, cy = p1.x(), p1.y()
        if is_station and sit_on_curve:
            # 弧顶会往内侧偏 r·sin(θ/2)/2 ⇒ 控制点往外侧挪同样的量，
            # 弧正好从站点身上过（站点精确落在线上）。
            dx, dy = -(u2x - u1x), -(u2y - u1y)    # 外侧
            m = (dx * dx + dy * dy) ** 0.5
            if m > 1e-6:
                d = r * math.sin(turn * 0.5) * 0.5
                cx += dx / m * d
                cy += dy / m * d
        a = QPointF(cx - u1x * r, cy - u1y * r)    # 拐点前 r 处
        b = QPointF(cx + u2x * r, cy + u2y * r)    # 拐点后 r 处
        path.lineTo(a)
        path.quadTo(QPointF(cx, cy), b)
    path.lineTo(points[-1])
    return path


def build_smooth_path(points: List[QPointF], tension: float = 1.0 / 6.0) -> QPainterPath:
    """
    Catmull-Rom 样条 → 三次贝塞尔，生成平滑曲线。
    曲线会精确经过每一个原始点。
    """
    path = QPainterPath()
    n = len(points)
    if n == 0:
        return path
    if n == 1:
        path.moveTo(points[0])
        return path
    if n == 2:
        path.moveTo(points[0])
        path.lineTo(points[1])
        return path

    path.moveTo(points[0])
    ext = [points[0]] + list(points) + [points[-1]]
    for i in range(len(ext) - 3):
        p0, p1, p2, p3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]
        c1 = QPointF(
            p1.x() + (p2.x() - p0.x()) * tension,
            p1.y() + (p2.y() - p0.y()) * tension,
        )
        c2 = QPointF(
            p2.x() - (p3.x() - p1.x()) * tension,
            p2.y() - (p3.y() - p1.y()) * tension,
        )
        path.cubicTo(c1, c2, p2)
    return path


# ------------------------------------------------------------
# 线路
# ------------------------------------------------------------

class MetroLineItem(QGraphicsPathItem):
    """一条地铁线路（粗彩色曲线）。不接收**鼠标按键**，避免挡住站点点击。

    ★ v2.6.12 起接收 **hover**（用户要求：鼠标悬浮在线路上时，和左侧图例
      悬停同一条线路的效果一致 —— 那条线加粗、其余变淡）。
      ⇒ 按键仍然一律不接（`setAcceptedMouseButtons(Qt.NoButton)`），
        否则会挡住"点空白拖地图 / 点站点"这两件事。
    """

    # 命中宽度（屏幕像素）。线本身只有 4.6px，正好沿着细线移很难命中，
    # 所以加宽到 12px；★ 用**固定值**而不是 `screen_width + N` ——
    # 高亮时 `screen_width` 会临时变成 8.0，用它算命中区会让"粘住"范围变化。
    HOVER_HIT_W = 12.0

    def __init__(self, line_id: str, color: str, parent=None):
        super().__init__(parent)
        self.line_id = line_id
        self.color = QColor(color)
        self.screen_width = SCREEN_LINE_W   # 屏幕像素线宽

        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        # ★ 按键一个都不接（不抢站点/空白的点击与拖动），但**要接 hover**
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setAcceptHoverEvents(True)
        self.setZValue(-5)

        # hover 回调：`(line_id, on) -> None`，由 MapView 注入。
        # ★ 为什么不用 Signal：`QGraphicsPathItem` 不是 `QObject`，发不了信号。
        self.hover_callback = None
        self._hover = False
        self._view_scale = 1.0
        self._shape_ver = 0
        self._shape_cache = None
        self._shape_key = None

        pen = QPen(self.color)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        self.setPen(pen)
        self.setBrush(QBrush(Qt.NoBrush))

    def set_points(self, points: List[QPointF], smooth: bool = True,
                   elbows: Optional[List[str]] = None) -> None:
        """
        smooth=True  → 八向布线（横/竖/45°，与原图一致）
        smooth=False → 原样直连（调试用）
        elbows       → 每段 45° 斜线贴哪一头（"a"/"b"），见 octilinear_waypoints_tagged
        """
        if smooth:
            self.setPath(build_octilinear_path(points, elbows=elbows))
        else:
            path = QPainterPath()
            if points:
                path.moveTo(points[0])
                for p in points[1:]:
                    path.lineTo(p)
            self.setPath(path)
        self._shape_ver += 1                 # ⇒ 命中区缓存作废
        self._shape_cache = None

    def line_boost(self) -> float:
        """线宽的**强调倍率**（1.0 = 正常）。

        ★★ 为什么改成"倍率"：v2.6.21 起线宽是**跟地图**的（场景恒定 22 + 屏幕下限），
          已经不存在一个"绝对的屏幕宽度"可以设了。
          但"悬浮时这条加粗、其余变淡"这个交互必须保留，所以让它按**比例**放大：
              正常 4.6 → 悬浮 8.0（×1.74）、隔离 5.4（×1.17）—— 比例沿用旧值。
        ★ 保留 `screen_width` 这个名字是为了不惊动既有回归
          （`_chk_line_hover` 直接读它），但它的语义已经变成"倍率的载体"。
        """
        return max(self.screen_width / SCREEN_LINE_W, 0.05)

    def apply_view_scale(self, scale: float) -> None:
        """按当前缩放把线宽换到场景单位。

        ★ v2.6.21：不再是"屏幕恒定"，而是**场景恒定 22 + 屏幕下限 3px**
          （理由见模块顶部 SCENE_LINE_W 那一段长注释）；再乘上强调倍率。
        """
        self._view_scale = scale
        pen = self.pen()
        pen.setWidthF(line_scene_width(scale) * self.line_boost())
        self.setPen(pen)

    # ---------------- hover 命中区 ----------------
    def shape(self) -> QPainterPath:
        """命中区域 = 沿路径加粗出来的**轮廓**，不是 boundingRect 那个大矩形。

        ★★ 必须重写：`QGraphicsPathItem` **没有**重写 `shape()`，默认返回
           **整个 boundingRect 的矩形**。一条斜穿全图的线路，boundingRect
           几乎覆盖全屏 ⇒ 鼠标在地图上任何位置都会"命中这条线"，
           悬浮高亮直接变成"一进地图就整屏变"（v2.6.12 第一次接 hover 就是这么炸的）。
        ★ 缓存：`shape()` 每移动一次鼠标就要被调 20 次（每条线一次），
           而 `QPainterPathStroker` 对几百段的路径描一次边并不便宜。
        """
        # ★ 缓存 key 用**量化后的命中带宽**而不是原始 `view_scale`：
        #   命中测试根本不需要那么精确，而 `view_scale` 是浮点数，
        #   连续缩放时每变一点点就全体失效 ⇒ 20 条线各重做一次 stroke。
        #   量化到 0.1 场景单位后，缩放过程中的大部分帧能直接复用。
        # ★ v2.6.21：线宽改成"跟地图"之后，命中带必须**至少和线一样宽**，
        #   否则放大后（线 22 场景单位）一条 12px 的命中带只有半条线宽，
        #   鼠标压在线的另一半上完全没反应 —— 这是改线宽最容易漏掉的一处。
        _s = max(self._view_scale, 0.01)
        hit_w = max(self.HOVER_HIT_W / _s, line_scene_width(_s) * self.line_boost(), 0.5)
        key = (self._shape_ver, round(hit_w, 1))
        if self._shape_cache is not None and self._shape_key == key:
            return self._shape_cache
        st = QPainterPathStroker()
        st.setWidth(hit_w)          # 场景单位 = 屏幕像素 / 缩放
        st.setCapStyle(Qt.RoundCap)
        st.setJoinStyle(Qt.RoundJoin)
        self._shape_cache = st.createStroke(self.path())
        self._shape_key = key
        return self._shape_cache

    def hoverEnterEvent(self, event):
        self._hover = True
        if self.hover_callback is not None:
            self.hover_callback(self.line_id, True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        if self.hover_callback is not None:
            self.hover_callback(self.line_id, False)
        super().hoverLeaveEvent(event)


# ------------------------------------------------------------
# 带白色描边的站名文字
# ------------------------------------------------------------

# ------------------------------------------------------------
# 站点图标（v2.6.67）：emoji（🚄 高铁站 / ✈️ 机场）+ 商场购物袋 PNG
#   · emoji 走 "Segoe UI Emoji"（Windows 自带，彩色渲染）；
#   · mall_* 用 assets/icons/mall_{red,gold,purple,green}.png（用户提供的图，
#     红→金→紫→绿 = 四个等级），打包经 build_exe.py 的 --add-data assets/icons。
#   · 位图按需求尺寸缓存（键 = (图标key, 像素)），重复绘制零成本。
# ------------------------------------------------------------
_ICON_EMOJI = {"hsr": "🚄", "airport": "✈️"}
ICON_GAP = 3.0            # 图标与站名文字之间的间隙（局部单位 == 屏幕像素）
_ICON_PM_CACHE: Dict[Tuple[str, int], QPixmap] = {}

# ------------------------------------------------------------
# v2.6.75：图标**类别 / 等级**可见性（主图右上角开关面板的数据源）
#   · 类别：商场 / 交通 / 酒店 / 豪宅（transport 含 🚄 与 ✈️ 两个"等级"）；
#   · 左键开关类别，右键菜单开关单个等级（见 ui/icon_toggle_panel.py）；
#   · 状态持久化在 view_settings.json 的 icon_visibility 键里；
#   · 默认全开 ⇒ 不过滤时行为与 v2.6.74 完全一致。
# ------------------------------------------------------------
ICON_CATEGORIES = [
    # (类别键, 中文名, emoji, [等级图标键...])
    ("mall", "商场", "🛍",
     ["mall_red", "mall_gold", "mall_purple", "mall_green"]),
    ("transport", "交通", "🚄",
     ["hsr", "airport"]),
    ("hotel", "酒店", "🏨",
     ["hotel_red", "hotel_gold", "hotel_purple", "hotel_green"]),
    ("mansion", "豪宅", "🏰",
     ["mansion_red", "mansion_gold", "mansion_purple", "mansion_green"]),
]
_ICON_KEY2CAT = {k: cat for cat, _n, _e, keys in ICON_CATEGORIES for k in keys}
# 等级的右键菜单显示名（没列出的按 颜色后缀 推 "红/金/紫/绿"）
ICON_LEVEL_LABELS = {"hsr": "高铁站", "airport": "机场"}
_LEVEL_SUFFIX = {"red": "红", "gold": "金", "purple": "紫", "green": "绿"}
# 豪宅占位色块（assets/icons/mansion_*.png 放进来后自动改用 PNG）
_MANSION_COLORS = {"red": "#D64550", "gold": "#D9A62E",
                   "purple": "#8E5AA8", "green": "#2FA46A"}

TAG_CAT_ON: Dict[str, bool] = {}     # 类别键 -> 是否显示（缺省 True）
TAG_LEVEL_ON: Dict[str, bool] = {}   # 图标键 -> 是否显示（缺省 True）


def tag_visible(key: str) -> bool:
    """某个图标键当前是否应该画出来（类别与等级两道闸都过才算过）。"""
    key = str(key or "")
    cat = _ICON_KEY2CAT.get(key)
    if cat is not None and not TAG_CAT_ON.get(cat, True):
        return False
    return TAG_LEVEL_ON.get(key, True)


def set_tag_visibility(cat_on: Dict[str, bool],
                       level_on: Dict[str, bool]) -> None:
    """整体替换可见性状态（来自开关面板 / view_settings.json）。"""
    TAG_CAT_ON.clear()
    TAG_CAT_ON.update(cat_on or {})
    TAG_LEVEL_ON.clear()
    TAG_LEVEL_ON.update(level_on or {})


def filtered_tags(tags) -> list:
    """按当前可见性过滤 tags 列表（HaloLabel.set_tags 前的一道闸）。"""
    out = []
    for t in tags or []:
        if not isinstance(t, dict):
            continue
        if not tag_visible(t.get("icon")):
            continue
        out.append(t)
    return out


def level_label(key: str) -> str:
    """等级的菜单显示名：先查专表（高铁站/机场），再按颜色后缀推。"""
    if key in ICON_LEVEL_LABELS:
        return ICON_LEVEL_LABELS[key]
    suf = str(key).rsplit("_", 1)[-1]
    return _LEVEL_SUFFIX.get(suf, key)


def icon_pixmap(key: str, px: int) -> Optional[QPixmap]:
    """站点图标的正方形透明底位图。key 空 / 未知返回 None（调用方跳过绘制）。"""
    px = max(8, min(512, int(px)))
    ck = (key, px)
    pm = _ICON_PM_CACHE.get(ck)
    if pm is not None:
        return pm
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    try:
        if key in _ICON_EMOJI:
            f = QFont("Segoe UI Emoji")
            f.setPixelSize(max(8, int(px * 0.9)))
            p.setFont(f)
            p.drawText(QRectF(0, 0, px, px), Qt.AlignCenter, _ICON_EMOJI[key])
        elif key.startswith(("mall_", "hotel_", "mansion_")):
            # v2.6.70：hotel_* = 酒店四色（红/金/紫/绿 楼房 PNG），与 mall_* 同机制
            # v2.6.75：mansion_* = 豪宅四色 —— 有 PNG 用 PNG，没有则画
            #   圆角色块 + "宅" 字占位（把 mansion_*.png 放进 assets/icons 即自动替换）
            try:
                from core.data_manager import _frozen_assets_dir
                path = _frozen_assets_dir() / "icons" / (key + ".png")
            except Exception:
                path = None
            src = QPixmap(str(path)) if path and path.exists() else QPixmap()
            if not src.isNull():
                p.drawPixmap(QRectF(0, 0, px, px), src,
                             QRectF(0, 0, src.width(), src.height()))
            elif key.startswith("mansion_"):
                suf = key.rsplit("_", 1)[-1]
                col = QColor(_MANSION_COLORS.get(suf, "#888888"))
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                r = px * 0.18
                p.drawRoundedRect(QRectF(px * 0.04, px * 0.04,
                                         px * 0.92, px * 0.92), r, r)
                f = QFont("Microsoft YaHei")
                f.setBold(True)
                f.setPixelSize(max(8, int(px * 0.52)))
                p.setFont(f)
                p.setPen(QColor("#FFFFFF"))
                p.drawText(QRectF(0, 0, px, px), Qt.AlignCenter, "宅")
    finally:
        p.end()
    _ICON_PM_CACHE[ck] = pm
    return pm


class HaloLabel(QGraphicsSimpleTextItem):
    """
    站名文字：先画一圈白色描边，再填深色字。

    为什么不用 QGraphicsSimpleTextItem 默认的 paint？
      默认只做纯色填充，压在彩色线路上会糊成一团。这里重写 paint，
      用同一条文字路径先描边再填充，两者天然对齐。

    boundingRect 额外留出描边的余量，避免重绘残影。
    """

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._halo = 0.0
        self._halo_color = QColor(255, 255, 255, 240)
        # 文字轮廓路径缓存：paint() 每帧都要用它，重建一次要几十毫秒。
        # 只有文字/字体变了才需要重建。
        self._path_cache: Optional[QPainterPath] = None
        self._path_key = None
        # ★ 离屏缓存：站名（带白描边）渲染一次就存起来，平移时直接贴图，
        #   不必每帧重新描边几百个汉字 —— 这是拖拽丝滑的关键。
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        # ★★ v2.6.69：站名前置**图标标签**（多组）。
        #   每组 = 图标 + 手动文字，可设图标在文字的 左/上/右/下；
        #   所有组依次排在**站名同一行前面**（随站名八向摆放/手拖偏移一起动）。
        #   self._tags = [(icon, text, pos)]（已归一化），_tag_px 为图标尺寸
        #   （标签局部单位 == 屏幕像素），由站点图元 apply_view_scale 按字号给定。
        self._tags: list = []
        self._tag_px: float = 0.0
        self._tags_sig: tuple = ()
        self._layout_cache = None
        self._layout_key = None

    def set_tags(self, tags, px_local: float) -> None:
        """设置/更新图标标签。tags 为 [{"icon","text","pos"}]；空列表 = 无标签。
        尺寸/内容都没变时直接返回（防抖，不炸缓存）。"""
        norm = []
        for t in (tags or []):
            if not isinstance(t, dict):
                continue
            ic = str(t.get("icon") or "")
            tx = str(t.get("text") or "").strip()
            pos = str(t.get("pos") or "left")
            if pos not in ("left", "right", "top", "bottom"):
                pos = "left"
            if not ic and not tx:
                continue
            norm.append((ic, tx, pos))
        px_local = max(0.0, float(px_local))
        sig = (tuple(norm), round(px_local, 2))
        if sig == self._tags_sig:
            return
        self.prepareGeometryChange()
        self._tags = norm
        self._tag_px = px_local
        self._tags_sig = sig
        self._path_cache = None
        self._layout_cache = None
        self.update()

    def has_tags(self) -> bool:
        """有没有图标标签（决定 _label_box 框宽走不走纯站名锁定宽）。"""
        return bool(self._tags)

    def _layout(self):
        """图标排版（局部单位）：v2.6.72 起**只画图标、不画标签文字** ——
        文字（商场/酒店名）只在鼠标悬浮图标时以 tooltip 显示（_tag_text_at）。

        摆放：pos=left 的图标排在站名左侧一行；right 排站名右侧；
        top/bottom 以站名中线为中心排成一行，悬在站名上/下方 2px。
        垂直约定：文字基线 y=ascent（与 _text_path 一致）；
        left/right 图标垂直中心 ≈ 0.55×ascent（视觉居中，旧经验公式）。
        返回 (icon_rects, text_xs, name_x) —— icon_rects 与 self._tags
        **一一对应**（无图标的组给空矩形）；text_xs 仅为签名兼容，恒为空表。
        """
        f = self.font()
        fm = QFontMetricsF(f)
        asc = float(fm.ascent())
        desc = float(fm.descent())
        ipx = self._tag_px
        gap_icon = float(ICON_GAP)
        gap_name = 5.0
        band_h = asc + desc
        nw = float(fm.horizontalAdvance(self.text()))
        icon_rects = [QRectF() for _ in self._tags]

        def row(indices, x0, y):
            x = x0
            for k in indices:
                icon_rects[k] = QRectF(x, y, ipx, ipx)
                x += ipx + gap_icon
            return x - (gap_icon if indices else 0.0)

        left_idx = [i for i, (ic, _tx, p) in enumerate(self._tags) if ic and p == "left"]
        right_idx = [i for i, (ic, _tx, p) in enumerate(self._tags) if ic and p == "right"]
        top_idx = [i for i, (ic, _tx, p) in enumerate(self._tags) if ic and p == "top"]
        bottom_idx = [i for i, (ic, _tx, p) in enumerate(self._tags) if ic and p == "bottom"]

        # left 行：占 [0, lw]，站名跟在右边 gap_name 处
        lw = row(left_idx, 0.0, asc * 0.55 - ipx / 2.0)
        name_x = lw + (gap_name if lw > 0.0 else 0.0)
        # right 行：站名右边 gap_name 起
        row(right_idx, name_x + nw + gap_name, asc * 0.55 - ipx / 2.0)

        def col_row(indices, y):
            if not indices:
                return
            total = len(indices) * ipx + (len(indices) - 1) * gap_icon
            row(indices, name_x + (nw - total) / 2.0, y)

        col_row(top_idx, -2.0 - ipx)          # top：底边贴文字上方 2px
        col_row(bottom_idx, band_h + 2.0)     # bottom：顶边贴文字下方 2px
        return icon_rects, [], name_x

    def set_halo_width(self, w: float) -> None:
        w = max(0.0, float(w))
        if abs(w - self._halo) < 0.01:
            return
        self.prepareGeometryChange()
        self._halo = w
        self.update()

    def halo_width(self) -> float:
        return self._halo

    def setFont(self, font) -> None:
        # ★ 字号没变就别动：setFont 会作废路径缓存，下一次 boundingRect/paint
        #   要重新排版几百个汉字 —— 缩放收尾时 379 个站全部命中"字号未变"，
        #   这里直接返回能把收尾耗时砍掉一大截。
        if font == self.font():
            return
        self._path_cache = None          # 字体变了，路径作废
        super().setFont(font)

    def setText(self, text: str) -> None:
        self._path_cache = None          # 文字变了，路径作废
        super().setText(text)

    def _layout_cached(self):
        """_layout() 带缓存（键 = 文字/字体/标签内容/图标尺寸）。"""
        f = self.font()
        key = (self.text(), f.family(), f.pixelSize(), f.bold(), f.weight(),
               round(self._tag_px, 2), tuple(self._tags))
        if self._layout_cache is not None and self._layout_key == key:
            return self._layout_cache
        lay = self._layout()
        self._layout_cache = lay
        self._layout_key = key
        return lay

    def boundingRect(self) -> QRectF:
        icon_rects, _text_xs, name_x = self._layout_cached()
        # 站名被整体右移 name_x；v2.6.72 起标签只画图标（无文字）——
        # 图标（尤其 top/bottom）可能上下出界 —— 逐个并进来。
        r = super().boundingRect().translated(name_x, 0)
        for ir in icon_rects:
            if not ir.isNull():
                r = r.united(ir)
        m = self._halo + 1.0
        return r.adjusted(-m, -m, m, m)

    def _text_path(self) -> QPainterPath:
        f = self.font()
        key = (self.text(), f.family(), f.pixelSize(), f.bold(), f.weight(),
               round(self._tag_px, 2), tuple(self._tags))
        if self._path_cache is not None and self._path_key == key:
            return self._path_cache
        _icon_rects, _text_xs, name_x = self._layout_cached()
        path = QPainterPath()
        baseline = float(QFontMetricsF(f).ascent())
        # v2.6.72：只画站名 —— 标签文字不再进路径（悬浮才显示，_tag_text_at）
        path.addText(QPointF(float(name_x), baseline), f, self.text())
        self._path_cache = path
        self._path_key = key
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        icon_rects, _text_xs, _name_x = self._layout_cached()
        for (ic, _tx, _pos), ir in zip(self._tags, icon_rects):
            if ic and not ir.isNull():
                pm = icon_pixmap(ic, int(round(self._tag_px * 2.0)))
                if pm is not None:
                    painter.drawPixmap(ir, pm,
                                       QRectF(0.0, 0.0, pm.width(), pm.height()))
        path = self._text_path()

        if self._halo > 0:
            pen = QPen(self._halo_color)
            pen.setWidthF(self._halo * 2.0)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        painter.setPen(Qt.NoPen)
        painter.setBrush(self.brush())
        painter.drawPath(path)


# ------------------------------------------------------------
# 站点
# ------------------------------------------------------------

# ------------------------------------------------------------
# 虚拟换乘 / 同名双站体之间的虚线
# ------------------------------------------------------------
# ★ 样式**照原图量出来的**（原图湖贝 2/5 号线之间那条，tools 实测）：
#     颜色 #8B8B8C（灰）、宽 11、实 12 / 空 9（场景单位 == 原图像素）
#   宽度正好是线路（22）的一半 —— 一眼能看出"这不是一条线，是一条通道"。
DASH_LINK_COLOR = "#8B8B8C"
SCENE_DASH_W = 11.0        # 虚线宽（场景单位）
DASH_ON = 12.0             # 实线段长（场景单位）
DASH_OFF = 9.0             # 空段长（场景单位）
SCREEN_DASH_MIN = 2.5      # 屏幕下限（px）：缩到整图时虚线仍然看得见


def dash_scene_width(scale: float) -> float:
    """当前缩放下虚线的**场景**宽度。跟线宽同一套路：场景恒定 + 屏幕下限。"""
    s = max(scale, 0.01)
    return max(SCENE_DASH_W, SCREEN_DASH_MIN / s)


# ★ "约XX米"这块小字可选的位置（相对两端中点）。原来它**死死待在中点**⇒
#   坪山那一片（坪山高铁站↔坪山 100m、未来城↔坪山广场 450m、坪山中心↔坪山中心
#   450m）三条字挤在一起，还压住"站前路东 / 坪山广场"的站名。用户原话
#   「你现在和原图好多都没有对照上。按照观看最佳的方式去修改」。
#   命名：`<方向><圈数>`，圈数 = 往外让几个"自身框"。
#   顺序 = 优先尝试顺序：中点 → 一圈四正 → 一圈四斜 → 二圈 → 三圈。
_LINK_DIRS = {
    "n": (0.0, -1.0), "s": (0.0, 1.0), "e": (1.0, 0.0), "w": (-1.0, 0.0),
    "ne": (0.7, -0.7), "nw": (-0.7, -0.7), "se": (0.7, 0.7), "sw": (-0.7, 0.7),
}
LINK_LABEL_SIDES = ("mid",) + tuple(
    "%s%d" % (d, i)
    for i in (1, 2, 3)
    for d in ("n", "s", "e", "w", "ne", "nw", "se", "sw"))
_SQRT1_2 = 0.70710678


class DashedLinkItem(QGraphicsItem):
    """两个站体之间的**灰色粗虚线**，中间可标"约XX米"。

    ★ 为什么需要它：深圳地铁有几种"要走出站换乘"的情况，官方图画法不一样，
      我们已经分好两类（见 data/stations.json 的顶层字段）：
        · `transfer_links`：**不同名**的两站（新澜↔观澜 等）——两站各自是普通站；
        · `alt_bodies`    ：**同名**的两个站体（湖贝 2号线 / 湖贝 5号线 等）。
      这两类原来都只在数据里，**渲染端一行都没写** ⇒ 图上完全看不出来。
      用户原话：「你没有把2号线和8号线连在一起？」「湖贝站我和你说过是
      重复显示的，中间用虚线连接」——就是这个漏掉的。

    ★ 它自己不参与命中/选中（线路和站点才是可点的），只做视觉。
    """

    def __init__(self, p0: QPointF, p1: QPointF, distance: str = "",
                 owners=(), parent=None):
        super().__init__(parent)
        self.p0 = QPointF(p0)
        self.p1 = QPointF(p1)
        self.distance = distance or ""
        # ★ 两端是哪些站（station_id）：隔离"只看某条线"时，据此决定这条虚线
        #   还该不该显示（见 MapView._restore_station_visibility）
        self.owners = tuple(owners)
        self._view_scale = 1.0
        self.setAcceptedMouseButtons(Qt.NoButton)
        # ★ z 序：线路 -5 < 虚线 -3 < 站点 10
        #   （虚线要压在线路上：同名两站体常常正好夹着一条线）
        self.setZValue(-3)
        self.label: Optional[HaloLabel] = None
        # ★ "约XX米"摆在哪儿：见 LINK_LABEL_SIDES。由 MapView 的防重叠排版决定，
        #   这样三条挨在一起的米数不会叠成一坨。
        self.label_side = "mid"
        if self.distance:
            self.label = HaloLabel(self.distance, self)
            self.label.setBrush(QBrush(QColor("#6B6B6D")))   # 比站名浅一点的灰
            # ★ 别用 setTextInteractionFlags —— 那是 QGraphicsTextItem 的接口，
            #   HaloLabel 继承的是 QGraphicsSimpleTextItem，没这个方法。
            self.label.setAcceptedMouseButtons(Qt.NoButton)

    # ---------------- 尺寸换算 ----------------
    def apply_view_scale(self, scale: float) -> None:
        self.prepareGeometryChange()
        s = max(scale, 0.01)
        self._view_scale = s
        pen = QPen(QColor(DASH_LINK_COLOR))
        w = dash_scene_width(s)
        pen.setWidthF(w)
        pen.setStyle(Qt.CustomDashLine)
        # ★ Qt 的 dash pattern 单位是**笔宽**，不是场景单位 ⇒ 要除以 w。
        #   这样虚线的"实/空"比例永远跟着线宽走，缩放时观感一致。
        pen.setDashPattern([DASH_ON / w, DASH_OFF / w])
        pen.setCapStyle(Qt.FlatCap)      # 原图是方块状虚线头，不是圆头
        self._pen = pen
        if self.label is not None:
            px = max(8, int(round(effective_font_px(s) * 0.85)))
            f = self.label.font()
            if f.pixelSize() != px:
                f = QFont("Microsoft YaHei")
                f.setPixelSize(px)
                f.setBold(True)
                self.label.setFont(f)
            ls = 1.0 / s                 # ★ 标签局部单位 = 屏幕像素
            self.label.setScale(ls)
        self._place_label()
        self.update()

    # ---------------- "约XX米"摆位 ----------------
    def label_mid(self, t: float = 0.5) -> QPointF:
        """虚线上的锚点。t=0.5 是两端中点（"mid" 档）。

        ★ v2.6.30：t 可以不是 0.5 —— 站名照抄原图方位之后，有的米数原来的
          落点被站名占了，而"换方向"最多只能让开 3 个框；沿虚线**滑动**一下
          （t=0.32 / 0.68）就躲开了，比继续往外让圈更贴着那条虚线。
        """
        return QPointF(self.p0.x() + (self.p1.x() - self.p0.x()) * t,
                       self.p0.y() + (self.p1.y() - self.p0.y()) * t)

    def label_size(self):
        """米数文字在**场景**里的宽高（= 屏幕像素 × 1/缩放）。"""
        if self.label is None:
            return 0.0, 0.0
        ls = 1.0 / max(self._view_scale, 0.01)
        lb = self.label.boundingRect()
        return lb.width() * ls, lb.height() * ls

    @staticmethod
    def _gap_scene(view_scale: float) -> float:
        """文字与虚线之间的呼吸 = 3 屏幕像素（换算成场景单位）。"""
        return 3.0 / max(view_scale, 0.01)

    def label_rect_for_side(self, side: str) -> QRectF:
        """按某个候选方向算出的**场景**矩形（不落盘，只算）。

        side = "mid" 或 `<方向><圈数>`（如 "n1" / "e2" / "ne3"）：
        圈数 = 往外让几个"自身框"（1 圈 = 刚好完全离开自己原来的位置）。
        ★ v2.6.30：后面还能挂 `@32` / `@68`，表示锚点沿虚线滑到 32% / 68%
        （默认 50%，见 label_mid）。
        """
        w, h = self.label_size()
        _t = 0.5
        if "@" in side:
            side, _ts = side.split("@", 1)
            try:
                _t = float(_ts) / 100.0
            except ValueError:
                _t = 0.5
        mid = self.label_mid(_t)
        if side == "mid" or w <= 0.0 or h <= 0.0:
            return QRectF(mid.x() - w * 0.5, mid.y() - h * 0.5, w, h)
        d = side.rstrip("0123456789")
        try:
            ring = float(side[len(d):] or "1")
        except ValueError:
            ring = 1.0
        ux, uy = _LINK_DIRS.get(d, (0.0, 0.0))
        gap = self._gap_scene(self._view_scale)
        sx = 1.0 if ux > 0 else (-1.0 if ux < 0 else 0.0)
        sy = 1.0 if uy > 0 else (-1.0 if uy < 0 else 0.0)
        diag = 0.75 if (sx and sy) else 1.0     # 斜向只要让 0.75 个框就够分开
        cx = mid.x() + sx * (w * 0.5 + gap) * ring * diag
        cy = mid.y() + sy * (h * 0.5 + gap) * ring * diag
        return QRectF(cx - w * 0.5, cy - h * 0.5, w, h)

    def set_label_side(self, side: str) -> None:
        if side == self.label_side:
            return
        self.prepareGeometryChange()      # ★ 先声明几何要变，再改
        self.label_side = side
        self._place_label()
        self.update()

    def _place_label(self) -> None:
        if self.label is None:
            return
        w, h = self.label_size()
        r = self.label_rect_for_side(self.label_side)
        # 注意：label 在局部坐标里是"1 单位 = 1 屏幕像素"，且已被 setScale(ls)，
        # 所以 pos() 要按场景坐标给（setScale 只影响子项自身的绘制缩放）。
        self.label.setPos(r.x(), r.y())

    # ---------------- 绘制 ----------------
    def _label_scene_rect(self) -> Optional[QRectF]:
        """米数文字在场景里的矩形（含一点点边距），供画白底用。"""
        if self.label is None:
            return None
        ls = 1.0 / max(self._view_scale, 0.01)
        lb = self.label.boundingRect()
        p = self.label.pos()
        pad = 3.0 * ls
        return QRectF(p.x() - pad, p.y() - pad,
                      lb.width() * ls + pad * 2, lb.height() * ls + pad * 2)

    def boundingRect(self) -> QRectF:
        r = QRectF(self.p0, self.p1).normalized()
        m = dash_scene_width(self._view_scale) * 0.5 + 2.0 * self._view_scale
        r = r.adjusted(-m, -m, m, m)
        lr = self._label_scene_rect()
        if lr is not None:
            r = r.united(lr)
        return r.adjusted(-1, -1, 1, 1)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        # ① 白底衬垫：先给米数文字铺一块白的，否则灰虚线从字缝里穿过去看不清
        lr = self._label_scene_rect()
        if lr is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(247, 249, 251, 235)))   # 底图色，半透明
            painter.drawRoundedRect(lr, 3.0 * self._view_scale,
                                    3.0 * self._view_scale)
        # ② 虚线本体（`_pen` 由 apply_view_scale 按缩放算好；没算过就现算一份）
        pen = getattr(self, "_pen", None)
        if pen is None:
            w = dash_scene_width(self._view_scale)
            pen = QPen(QColor(DASH_LINK_COLOR))
            pen.setWidthF(w)
            pen.setStyle(Qt.CustomDashLine)
            pen.setDashPattern([DASH_ON / w, DASH_OFF / w])
            pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(self.p0, self.p1)


# ------------------------------------------------------------
# 线路末端的"线路号方块"
# ------------------------------------------------------------
# ★ 样式**照原图量出来的**（tools/_measure_badges.py 距离变换量尺 +
#   tools/_ascii_view.py 字符画复核）：
#     圆角方块（圆角 ≈ 边长 × 0.18）、底色 = 线路色、白色粗体数字，
#     边长 ≈ **125** 场景单位（原图像素；实测 20 个方块都在 124~126），
#     摆在终点站**往外**约 183px 处（实测中位数；罗湖 119、福田口岸 184、太安 209）。
#   用户原话：「给不同的线路末端补上对应的线路号，参考原图」。
#   福田口岸是唯一的双号端点，原图实测：红"4" 与 粉"10" 并排在两个独立站体下方，
#   两个方块中心相距 136 ⇒ 缝 = 136 - 125 = 11。
# ★★ 第一版把边长拍成 78、间距拍成 26，纯属没量就写 —— 差了近一倍。
BADGE_SCENE = 125.0        # 方块边长（场景单位 == 原图像素）
BADGE_SCREEN_MIN = 16.0    # 屏幕下限（px）：缩到整图时还认得出是个线路号
BADGE_GAP = 112.0          # 方块与站点之间的间隙（125/2 + 112 ≈ 175 ≈ 原图均值 174）
BADGE_SPREAD = 11.0        # 同一个端点有多个线路号时，相邻两个之间的缝（136 - 125）


def badge_scene_size(scale: float) -> float:
    """当前缩放下线路号方块的**边长**（场景单位）。跟药丸同一套路：场景恒定 + 屏幕下限。"""
    return max(BADGE_SCENE, BADGE_SCREEN_MIN / max(scale, 0.01))


class TerminalBadgeItem(QGraphicsItem):
    """线路末端的线路号方块（纯展示，不吃鼠标）。

    ★ 为什么不复用左侧图例：图例是"看线号查颜色"，而原图在**每条线的终点**
      又放一个方块，作用是"一眼看出这条线到这儿就完了"。两者位置/用途都不同。
    """

    def __init__(self, text: str, color, parent=None):
        super().__init__(parent)
        self.text = str(text)
        self._color = QColor(color)
        self._scale = 1.0
        # ★ 位置不是写死的绝对坐标，而是"相对终点站"的描述：
        #   缩小时方块按屏幕下限变大（场景里变大），跟站的间隙也得跟着变大，
        #   否则会压到站点上。所以把 anchor/方向/第几格存下来，每次缩放重算。
        self._anchor = QPointF(0.0, 0.0)   # 终点站坐标
        self._dir = (0.0, 1.0)             # 外向单位方向
        self._dist = BADGE_SCENE * 0.5 + BADGE_GAP   # 中心离站体的距离（场景单位）
        self._lane = 0.0                   # 同一端点多个方块时的"第几格"（0 = 居中）
        # ★★ v2.6.34：用户可以**手动拖**这个方块（原话「线路的标志号也改为可以
        #   移动位置」）。偏移是**场景单位**（不是屏幕像素）—— 方块的位置本来
        #   就是"离终点站多远"这种场景量，拖完就该牢牢钉在地图上，
        #   跟站点一起缩放平移。存 `data/badge_offsets.json`，键跟
        #   `terminal_badges.json` 一样是 `<线号>|<站名>`。
        self._off = QPointF(0.0, 0.0)
        self.badge_key = ""                # "<线号>|<站名>"，落盘用
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setAcceptHoverEvents(False)
        # 线路 -5 < 线路号 -2 < 虚线 -3 …其实这里只要求"压在线上、不压站点"：
        # 方块摆在站外空地上，正常不会和站点打架，所以取 -2（在线路之上）。
        self.setZValue(-2)

    def set_layout(self, ax: float, ay: float, ux: float, uy: float,
                   dist: float, lane: float = 0.0) -> None:
        """登记"该摆在哪"：终点站 (ax,ay)、外向单位方向 (ux,uy)、中心距离 dist
        （照原图量出来的；没量到时走 `dist=BADGE_SCENE/2+BADGE_GAP` + 并排格 lane）。
        """
        self._anchor = QPointF(ax, ay)
        self._dir = (ux, uy)
        self._dist = dist
        self._lane = lane

    def _relayout(self) -> None:
        s = self.size_scene()
        ux, uy = self._dir
        px, py = -uy, ux                       # 垂直方向（用来并排）
        # ★ 方块按屏幕下限变大时，保持"方块与站之间的缝"恒定（只把多出来的
        #   边长算进距离），不然缩到底会压到站点上。
        gap = max(self._dist - BADGE_SCENE * 0.5, 0.0)
        off = self._lane * (s + BADGE_SPREAD)
        self.setPos(self._anchor.x() + ux * (s * 0.5 + gap) + px * off
                    + self._off.x(),
                    self._anchor.y() + uy * (s * 0.5 + gap) + py * off
                    + self._off.y())

    # ---------- v2.6.34：方块可以手动拖 ----------
    def badge_off(self) -> QPointF:
        """相对"自动摆位"的偏移（**场景单位**）。"""
        return self._off

    def has_badge_off(self) -> bool:
        return abs(self._off.x()) > 0.01 or abs(self._off.y()) > 0.01

    def set_badge_off(self, dx: float, dy: float) -> None:
        dx, dy = float(dx), float(dy)
        if (abs(dx - self._off.x()) < 0.01 and abs(dy - self._off.y()) < 0.01):
            return
        self.prepareGeometryChange()
        self._off = QPointF(dx, dy)
        self._relayout()
        self.update()

    def size_scene(self) -> float:
        return badge_scene_size(self._scale)

    def apply_view_scale(self, scale: float) -> None:
        self.prepareGeometryChange()      # ★ 先声明几何要变，再改
        self._scale = max(scale, 0.01)
        self._relayout()
        self.update()

    def boundingRect(self) -> QRectF:
        h = self.size_scene() * 0.5 + 1.0
        return QRectF(-h, -h, h * 2, h * 2)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        h = self.size_scene() * 0.5
        r = QRectF(-h, -h, h * 2, h * 2)
        radius = h * 2 * 0.18
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._color))
        painter.drawRoundedRect(r, radius, radius)
        painter.setPen(QPen(QColor("#FFFFFF")))
        f = QFont("Microsoft YaHei")
        # ★ 两位数（"10"/"6支"）得缩字号，否则两个数字会撑出方块外
        #   —— 原图福田口岸粉"10"：方块的白字区宽 ≈ 方块宽的 0.7。
        k = 1.12 if len(self.text) <= 1 else 0.72
        f.setPixelSize(max(2, int(round(h * k))))
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(r, Qt.AlignCenter, self.text)


# ------------------------------------------------------------
# ★ v2.6.89：🔒 站点锁定（工具栏按钮控制）
#   True = 鼠标**拖不动**站点圆点 / 副站体圆点（程序化 setPos 不受影响，
#   所以撤销/重做/重载照常工作）。放在模块级而不是图元属性上：
#   itemChange 每次拖动都会进来（一帧多次），查模块级布尔比
#   scene().views() 便宜得多。
# ------------------------------------------------------------
STATIONS_LOCKED = False


def set_stations_locked(on: bool) -> None:
    global STATIONS_LOCKED
    STATIONS_LOCKED = bool(on)


# ★ v2.7.10：选中态 = **红色实心 + 红色站名**（用户原话：「选中的站点变为红色，
#   即变红加闪烁，只要没有取消选择则保持红色」）。
#   为什么是"填充"不是"光晕"：光晕闪完就没了，用户要的是"只要没取消就一直红"。
#   ★ 颜色取官方图里 4 号线的红 #E01010 —— 跟地铁配色同一套，不会显得突兀。
SELECTED_FILL = "#E01010"
SELECTED_EDGE = "#8E0A0A"   # 比填充深一点：纯红上加纯红看不出轮廓
LABEL_COLOR_NORMAL = "#111827"
# ★ v2.7.11：圆点外面那圈**红色圆环**（用户原话「改为红色圈闪烁，文字不闪烁」，
#   并确认"圆点仍填红"）。闪烁 = 这圈红环亮/灭；站名文字**不再变色、不再闪**。
RING_W_PX = 2.4        # 环的线宽（屏幕像素）
RING_OFF_PX = 3.0      # 环离圆点边缘的间隙（屏幕像素）


class StationDotItem(QGraphicsObject):
    """
    站点圆点 + 站名。
    尺寸随缩放自动换算，保证屏幕上大小恒定。
    站名方向（右/左/上/下）由 MapView 的防重叠排版决定。
    """

    def __init__(self, station_id: str, data: Dict, color: Optional[QColor] = None, parent=None):
        super().__init__(parent)
        self.station_id = station_id
        self.data = data
        self._color = color or QColor("#444444")
        self._hover = False
        self._selected = False
        self._blink = False           # ★ v2.6.90：搜索定位闪烁（光晕 + 文字一起闪）
        self._view_scale = 1.0
        self._label_ls = 1.0          # 标签自身缩放（局部单位 = 屏幕像素）
        self._label_on = True
        # ★★ v2.6.29：站名的**初始方位照原图**（tools/measure_label_side.py 逐个量出来，
        #   365 站：right 122 / top 67 / left 47 / bottom 33 / lt 32 / rt 27 / rb 21 / lb 16）。
        #   用户原话「文字根本就没有严格跟随站点，请把文字和地铁图中严格对照位置，
        #   文字到底是在站点圆圈的上下左右哪里对照好了」。
        #   排版器（MapView._update_label_visibility）是"稳定性优先"的，它第一个试的
        #   就是当前这一侧 ⇒ 给对了初始值，绝大多数站名就会停在原图那个方位；
        #   只有在真会撞车时才让开（那也是原图做不到的情况下的次优解）。
        _ols = data.get("official_label_side") or "right"
        self._label_side = _ols if _ols in LABEL_SIDES else "right"
        # ★★ v2.6.60：**手动拖过站名的站，方位必须跟着一起存/读** —— 只存偏移
        #   （label_dx/dy）是不够的：最终位置 = 方位摆位 + 偏移，而"方位"以前
        #   只活在内存里（`_side_lock`），重开时排版器见到"有偏移"就**直接放行**、
        #   不再给它挑方位 ⇒ 方位退回初始值 ⇒ 基点换了一个，偏移叠上去就差出
        #   几十像素。用户原话：「每次修改文字位置后再打开会丢失正确位置」。
        #   实测（tools/_repro_label_lost.py）：上屋 拖动时 side=right1、重开变 right
        #   ⇒ 同一个偏移 (60,-80)，位置差 60px。
        _ls = str(data.get("label_side") or "")
        # 变异开关（回归 _chk_label_persist 用）：=1 退回 v2.6.59 的"只存偏移不存方位"
        if (_ls and split_label_ring(_ls)[0] in LABEL_SIDES
                and os.environ.get("METROEDITOR_NO_LABEL_SIDE", "0") != "1"):
            self._label_side = _ls
        # ★★ v2.6.32：站名跟圆点**分离** —— 站名可以被单独拖到任意位置。
        #   拖出来的偏移存 `label_dx / label_dy`（stations.json，跟 x/y 同级）。
        #   单位是**屏幕像素**（不是场景单位）：站名框本身就是"屏幕尺寸恒定"的
        #   东西（字号/间距都不随缩放变），偏移也跟着屏幕走 ⇒ 缩放时站名和圆点
        #   的相对位置纹丝不动，不会"放大了字飞到天边"。
        #   有偏移的站 ⇒ 排版器彻底不管它（`MapView.try_place` 见到就放行）。
        self._label_off = QPointF(float(data.get("label_dx") or 0.0),
                                 float(data.get("label_dy") or 0.0))
        # ★ v2.6.41：右上角「字体缩放」滑块 —— 字号倍率 / 锁定的屏幕字号
        self._font_mul = 1.0
        self._font_lock_px = None      # 非 None = 锁死在这个屏幕字号上
        # 缩放动画用 sprite 缓存：(QPixmap, 圆点中心x, 圆点中心y)（逻辑像素）。
        # 由 render_sprite() 生成；几何/文字/状态一变即置 None，下次按需重建。
        self._sprite: Optional[Tuple[QPixmap, float, float]] = None
        # ★ sprite 内容签名：与 _sprite 同时有效（_sprite 为 None 时签名无意义）。
        #   屏幕呈现尺寸恒定 → 决定 sprite 像素的只有【量化后的屏幕量】：
        #   屏幕字号/描边/标签屏幕偏移/显示开关/悬停选中/文字。缩放只要不跨
        #   这些量化档位，sprite 像素完全相同 → 直接跳过重建（收尾从 750ms 归零）。
        self._sprite_sig = None
        # ★ 按下那一刻的位置：松手时用它判断"这次到底有没有真的拖动过"
        #   （见 mousePressEvent / mouseReleaseEvent 的长注释）
        self._press_pos: Optional[QPointF] = None

        self.is_transfer = bool(data.get("is_transfer"))

        # ★ v2.6.20：药丸几何来自原图实测（data/stations.json 的 `pill` 字段）
        #   pill = {"ang": 0~180（0=横 90=竖 45/135=斜）, "len": 原图内部长, "wid": 原图内部宽}
        #   ★ len/wid 的单位是**场景单位（= 原图像素）**：因为各条线的走廊偏移
        #     也是按原图像素算的，药丸必须用同一把尺子才量得准"跨过几条走廊"。
        #   缺数据时退回 v2.6.19 的老样子（竖、25×48）。
        _p = data.get("pill") or {}
        try:
            self._pill_ang = float(_p.get("ang", 90.0)) % 180.0
            self._pill_len = float(_p.get("len", 50.0))
            self._pill_wid = float(_p.get("wid", 26.0))
        except (TypeError, ValueError):
            self._pill_ang, self._pill_len, self._pill_wid = 90.0, 50.0, 26.0
        if self._pill_wid <= 1.0:
            self._pill_wid = 26.0
        # ★ v2.6.65：胶囊**中心偏移**（场景单位，pill.dx/dy，缺省 0）。
        #   福田口岸这类"横向胶囊把同名双站体连成一体"的站，胶囊中心不在站
        #   坐标上，而在主/副站体中点 ⇒ 画的时候平移过去。偏移同时参与
        #   screen_half（AABB）/ boundingRect，保证命中、光晕、站名避让都跟着走。
        #   dx/dy 缺省 0 ⇒ 其余换乘站几何分毫不变。
        try:
            self._pill_dx = float(_p.get("dx", 0.0) or 0.0)
            self._pill_dy = float(_p.get("dy", 0.0) or 0.0)
        except (TypeError, ValueError):
            self._pill_dx = self._pill_dy = 0.0
        # 该站在各线上的「走廊偏移」（原图像素 == 场景单位）：由 MapView 建线时用
        self.lane_offsets = data.get("lanes") or {}

        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        # ★ v2.6.55：要接管"位置被改"这件事（乙：拖站点吸到原图走廊），
        #   必须先开 ItemSendsGeometryChanges，否则 itemChange 收不到位置通知。
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self._snapping = False        # 只在**拖动中**才吸附（见 mousePressEvent）
        self.setZValue(10)
        self.setCursor(Qt.PointingHandCursor)
        # ★ 离屏缓存：圆点在屏幕上大小恒定，缓存一次即可反复贴图（平移时省大量重绘）
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

        # 站名（带白描边；加粗）
        self.label = HaloLabel(self._display_name(), self)
        self.label.setBrush(QBrush(QColor(LABEL_COLOR_NORMAL)))
        # ★ v2.6.54：这站名字在**参考字号**下的"每像素字宽"（跨倍率恒定的尺子）
        self._ref_ratio = ref_text_width_per_px(self._display_name())
        self._box_w = 0.0          # ★ v2.6.54：归一化的框宽（场景单位，跨倍率恒定）
        # 让鼠标事件穿透站名，落到圆点/地图上（否则点站名无法拖动地图）
        self.label.setAcceptedMouseButtons(Qt.NoButton)
        self.label.setZValue(11)

        self.setPos(QPointF(float(data.get("x", 0)), float(data.get("y", 0))))
        self.apply_view_scale(1.0)

    # ---------- 尺寸换算 ----------
    def lane_span_along(self, ang_deg=None) -> float:
        """该站并排走廊在**药丸长轴方向**上的跨度（场景单位）。

        ★ v2.6.25：药丸唯一的作用就是"横跨并排走廊把它们串起来"，所以它的长度
          **必须由走廊跨度决定**（见 pill_half 里的 need）。少了这个数，就只能拿
          固定屏幕像素当下限 —— 缩小时药丸和走廊各缩各的，比例失控。
        ★ 只投影到长轴方向：走廊是沿长轴方向排开的（车公庙 7/9/11 在 x 偏
          −49/+6/+51，药丸是横的 ⇒ 沿 x 量，跨度 100）。
        """
        a = math.radians(self._pill_ang if ang_deg is None else ang_deg)
        ux, uy = math.cos(a), math.sin(a)
        vals = []
        for _lid, d in (self.lane_offsets or {}).items():
            try:
                vals.append(float(d[0]) * ux + float(d[1]) * uy)
            except (TypeError, ValueError, IndexError):
                pass
        if len(vals) < 2:
            return 0.0
        return max(vals) - min(vals)

    def pill_half(self, scale: Optional[float] = None) -> tuple:
        """药丸**白心**沿自身两个轴的半尺寸（屏幕像素）：(半宽, 半长)。

        ★ v2.6.31：多了个 `scale` 参数 —— 传了就按**它**算，不传才用图元自己的
          `_view_scale`。缩放动画的合成帧必须传当前虚拟缩放：动画期间图元是
          隐藏的、`_view_scale` 冻结在手势起点，只有显式传才能算出连续的尺寸。

        ★ v2.6.20：按**场景尺寸**算，只在下方夹一个"屏幕下限"。
          为什么不能只按屏幕算：药丸的作用是"横跨几条并排走廊把它们串起来"，
          而走廊间距（约 50 场景单位）是跟着地图走的 —— 只按屏幕算的话，
          缩小时药丸会长得离谱（比走廊还长好几倍），放大时又够不到最外侧走廊。
          为什么要有下限：缩到整图时药丸只有几个像素，会缩成一个看不清的点，
          而下限正好等于 v2.6.19 用户认可的"大药丸"尺寸。
        ★★ 为什么**不设上限**：第一版在上方夹了"缺省值的 3 倍"，结果视图缩放
          超过约 0.6 倍以后药丸就停止长大，而走廊还在按地图变宽 ——
          实测 2 倍时两条走廊相距 200 屏幕px、药丸却只有 80px，中间断开，
          正是用户抱怨的"没连起来"。药丸要么完全跟地图（走廊一定连得上），
          要么完全跟屏幕（大小可控）—— 这里选**跟地图**，因为"连不上"是硬伤；
          放大后药丸变大是忠实反映地图自身比例（原图 1:1 时它也就是这么大）。
          实测：视图缩放 0.54 时药丸尺寸与原图**完全一致**。
        ★★ 这里返回的是**白心**（= data 里 pill.wid/len 的语义），
           **不含**那圈 7 单位的黑描边 —— 描边是绘制时才补的（见 paint / _paint_transfer_pill）。
          第一版把描边算进这里的返回值，结果所有"探测点该落在白心上"的回归全挂
          （探到了黑边），长宽比也被描边带偏（135/33 vs 原图 128/26）。
          ⇒ **尺寸的"语义"要单一**：这个函数永远只谈白心，包围盒/描边各自去加。
        """
        s = max(self._view_scale if scale is None else scale, 0.01)
        if not self.is_transfer:
            # ★★ v2.6.30：普通站也要**跟场景**（原图半径 11 × scale），
            #   只在缩到很小时用四次幂平均保底到 3.4 屏幕px（跟药丸同样的手法，
            #   平滑、不会在缩放动画里"弹一下"）。
            #   A/B：METROEDITOR_NORMAL_R_SCENE=0 退回 v2.6.29 的屏幕恒定写法。
            r = normal_dot_screen_r(s)
            return r, r
        hw = self._pill_wid * 0.5 * s
        hl = self._pill_len * 0.5 * s
        # ★★ v2.6.24：下限必须**等比**放大，不能一个轴一个轴各自夹。
        #   用户原话「并不是所有中转站示例的胶囊都一样大，重新修改调整」。
        #   旧写法 hw=max(hw,RX)、hl=max(hl,RY)：缩到 0.2 倍时
        #   科学馆(26×50) 与车公庙(26×128) 双双被夹到 14×26.8 屏幕px
        #   —— **大小完全一样了**，原图里它们差 2.5 倍。
        #   现在改成"先算需要放大的倍数，再两轴一起乘"，长宽比永远不变：
        #   同一档缩放下车公庙仍然是科学馆的 2.56 倍长。
        if os.environ.get("METROEDITOR_NO_PILL_PROP", "0") == "1":
            # A/B 开关：退回 v2.6.23「一个轴一个轴各自夹」的旧写法
            return max(hw, SCREEN_TRANSFER_RX), max(hl, SCREEN_TRANSFER_RY)
        # ★★★ v2.6.25：长轴长度 = 走廊跨度/2 + 线宽/2 + PILL_OVER。
        #   用户原话「胶囊的左右刚好遮住线路图左和右一点，你现在完全是乱搞比例」。
        #   v2.6.24 的"等比放大"保住了长宽比，但放大倍数来自固定像素下限，
        #   跟走廊无关 ⇒ 缩放 0.1 时车公庙半长 34.4px、走廊外缘只有 6.1px（宽 5 倍）。
        #   原图画法：车公庙长 128 = 走廊跨 100 + 线宽 22 + 两端各 3 ⇒ 本式。
        span = self.lane_span_along()
        need = (span * 0.5 + LINE_W_SCENE * 0.5 + PILL_OVER) * s
        # ★★ v2.6.28：下限改成**平滑**的（四次幂平均），不再用 max() 硬夹。
        #   为什么：max() 会在 hw 正好跨过 RX 的那一刻**折一下** —— 缩放动画期间
        #   画面走的是"场景快照 × 临时缩放"（药丸尺寸还没重算），收尾时才换成
        #   新尺寸，于是那一折就变成"药丸尺寸跟不上、松手才弹一下"的滞后感
        #   （用户原话「胶囊跟随缩放的延迟太高了」）。
        #   四次幂平均在 hw >> RX 时只大 0.1%（实测 0.54 档 13.00 → 13.01，
        #   跟原图一致的那条判据不会被破坏），在 hw << RX 时平滑过渡到 RX。
        # ★★ v2.6.54：这个"屏幕最小半径"保底**默认关掉**（跟 v2.6.43 关掉的那三个
        #   物理下限同一类：屏幕恒定量 = 等比的对立面）。
        #   它是"换乘站站名换个倍率就漂"的最后一块：小档把药丸在**场景里撑大**
        #   ⇒ 站名为了不压上去被推远（实测"宝安中心"在 0.115 档比 0.4 档远 37
        #   场景单位，而 0.4 档以上完全稳定）—— 因为它只在 hw << RX 时才起作用。
        #   ★ v2.6.25 的定案是"药丸**跟地图**"（跟走廊连得上才是硬伤），
        #     屏幕保底跟这条定案本身也是冲突的。
        if PHYSICAL_MINS or os.environ.get("METROEDITOR_PILL_HARD_MIN", "0") == "1":
            if os.environ.get("METROEDITOR_PILL_HARD_MIN", "0") == "1":
                hw = max(hw, SCREEN_TRANSFER_RX)      # A/B：退回硬夹
            else:
                hw = (hw ** 4 + SCREEN_TRANSFER_RX ** 4) ** 0.25
        hl = max(hl, need, hw * PILL_MIN_RATIO)
        return hw, max(hl, hw)

    def pill_border_screen(self, scale: Optional[float] = None) -> float:
        """那圈黑描边在屏幕上的厚度（含下限，避免缩太小看不见）。"""
        if not self.is_transfer:
            return 0.0
        s = self._view_scale if scale is None else scale
        return TRANSFER_PILL_BORDER * max(s, 0.01)

    def screen_half(self, scale: Optional[float] = None) -> tuple:
        """**轴对齐包围盒**的半宽/半高（屏幕像素）。

        ★ v2.6.20：药丸有方向（横/竖/斜），所以「包围盒」≠「药丸自身」。
          · 竖药丸（ang=90）：AABB == 自身；
          · 横药丸（ang=0） ：AABB 半宽 = 半长、半高 = 半宽；
          · 斜药丸（ang=45） ：两者都是 (半宽+半长)/√2。
          站名间距、_label_box()、boundingRect() 一律用 AABB —— 若拿药丸
          自身尺寸去算，横药丸左右的站名会**压在药丸上**（实测差 4 倍）。
        ★ 外廓 = 白心 + 一圈描边，所以这里把描边整个加上，
          否则站名会紧贴甚至压到那圈黑边上。
        """
        hw, hl = self.pill_half(scale)
        if not self.is_transfer:
            return hw, hl
        a = math.radians(self._pill_ang)
        c, s = abs(math.cos(a)), abs(math.sin(a))
        bb = self.pill_border_screen(scale)
        rx, ry = hw * s + hl * c + bb, hw * c + hl * s + bb
        # ★ v2.6.65：胶囊中心偏移（福田口岸横向胶囊跨双站体）——
        #   AABB 相对**站坐标**原点的半宽/半高要把偏移也算进去，
        #   否则站名避让/包围盒/命中都还围着旧中心转。
        if self._pill_dx or self._pill_dy:
            sv = self._view_scale if scale is None else scale
            rx += abs(self._pill_dx) * sv
            ry += abs(self._pill_dy) * sv
        return rx, ry

    def pill_angle(self) -> float:
        """药丸长轴与水平线的夹角（度，屏幕坐标系：0=横 90=竖）。"""
        return self._pill_ang

    def screen_radius(self) -> float:
        """包围半径（屏幕像素）：取半宽/半高中较大者，供包围盒与光晕用。"""
        rx, ry = self.screen_half()
        r = max(rx, ry)
        if self._hover:
            r += 2.0
        if self._selected:
            r += 1.0
        return r

    def radius(self) -> float:
        """场景坐标半径。"""
        return self.screen_radius() / max(self._view_scale, 0.01)

    def text_scale_factor(self) -> float:
        return 1.0 / max(self._view_scale, 0.01)

    def screen_font_px(self) -> float:
        """当前站名的**屏幕**字号。

        ★ v2.6.41：右上角「字体缩放」滑块的两个效果 ——
          · 倍率 `_font_mul`：在等比字号上再乘一个系数（想整体调大/调小字）；
          · 锁定 `_font_lock_px`：非 None 时**无视缩放**，永远用这个屏幕字号
            （= v2.6.38 之前"字不随图放大"的行为）。
        """
        if self._font_lock_px:
            return self._font_lock_px
        return effective_font_px(self._view_scale) * self._font_mul

    def set_font_opts(self, lock_px, mul: float) -> None:
        """由 MapView 统一下发（滑块改一次就给全部站点设一遍）。"""
        self._font_lock_px = lock_px
        self._font_mul = float(mul)

    def label_scale(self) -> float:
        """标签图元自身的缩放（= 1/视图缩放，让标签局部单位 == 屏幕像素）。

        ★ 缓存成 Python 属性而不是每次问 self.label.scale()：防重叠排版里
          _label_box() 会被调用上万次（379 站 × 8 个方向 × 碰撞探测），
          每次多一次 Python→C++ 调用实测能差出好几毫秒。
        """
        return self._label_ls

    # ---------- 站名布局（四向） ----------
    def label_side(self) -> str:
        return self._label_side

    def _label_box(self, side: Optional[str] = None,
                   scale: Optional[float] = None) -> QRectF:
        """站名矩形（item 坐标系）。side 为空时用当前方向。

        ★ label.boundingRect() 是**标签局部**坐标（= 屏幕像素），乘 label_scale()
          才换算成 item 坐标。忘了乘就会出现"排版按错误尺寸算重叠"。
        """
        lb = self.label.boundingRect()
        ls = self.label_scale()
        # ★★ v2.6.83：带图标标签的框宽必须**含图标行**（boundingRect 在 v2.6.69
        #   起已并进 icon_rects 并平移 name_x）。以前这里无条件用 _box_w（纯站名
        #   锁定宽）⇒ 框比涂装窄一半以上：实测后海 涂装 320 vs 框 108 ——
        #   ① _label_hit 拖字点不中看得到的站名文字（用户：「带图标的文字都无法
        #      拖动」，点文字反而拖走圆点）；② 防重叠排版按错宽度算（图标压线/压邻标）。
        #   没图标的站维持 _box_w 锁定（hinting 补偿逻辑不变）。
        w = self._box_w if (LABEL_BOX_LOCK and self._box_w > 1e-6
                            and not self.label.has_tags()) else lb.width() * ls
        h = lb.height() * ls
        # ★ v2.6.20：screen_half() 给的是轴对齐包围盒 —— 横药丸水平方向是"半长"。
        #   所以左右两侧站名会被推到药丸真正的边缘外，不会压上去。
        _vs = self._view_scale if scale is None else scale
        rx, ry = self.screen_half(scale)
        # ★★ v2.6.21：把"站名要站到线宽外面"这条并进来 —— 圆点比线还窄时，
        #    按圆点算出来的位置会让字的近边陷进线里（见 LABEL_LINE_CLEARANCE 注释）。
        _lh = line_screen_width(_vs) * 0.5
        rx, ry = max(rx, _lh), max(ry, _lh)
        k = 1.0 / max(_vs, 0.01)
        RX, RY = rx * k, ry * k
        # ★★ v2.6.30：这里原来是 `max(SCREEN_LABEL_GAP * k, LABEL_LINE_CLEARANCE)`
        #   —— **两个项的单位不一样**，就是"文字离圆点太远 / 缩放全错位"的病根：
        #     · SCREEN_LABEL_GAP * k：4 屏幕px 换算成场景（÷scale）⇒ 屏幕上恒定 4px；
        #     · LABEL_LINE_CLEARANCE：v2.6.21 从原图量出来的"站名到线边缘净空 9"，
        #       那是**原图像素 = 场景单位**，被当成场景常量直接用了 ⇒
        #       屏幕上 = 9 × scale：放大 8 倍时字被推到离圆点 72 屏幕px 远（越放越远）。
        #   两项必须**同一个量纲**再取 max。让开线宽这件事已经由上面 rx/ry 的
        #   `max(圆点半宽, 线宽一半)` 办了，这里只需要一段屏幕恒定的呼吸量。
        # ★★ v2.6.42：gap 改成**场景单位**（原图尺子），不再 × k。
        #   × k 那套是"屏幕上恒定 4px" —— v2.6.38 把字和线都改成等比之后，
        #   就只剩这个间距还是固定像素 ⇒ 放大时线长到 44px、间隙还是 4px
        #   （间隙/线宽 从 61% 塌到 9%）⇒ 用户：「放大会导致文字离线路越来越近
        #   直到贴到线路上，缩小却越来越远」。改成场景后这个比例**恒定 36%**，
        #   和照片一样。★ 数值取 8（原图实测"站名到线边缘净空"最小 9、中位 28）。
        gap = LABEL_GAP_SCENE
        s = side or self._label_side
        base, ring = split_label_ring(s)
        s = base
        if s == "left":
            x, y = -RX - gap - w, -h / 2
        elif s == "top":
            x, y = -w / 2, -RY - gap - h
        elif s == "bottom":
            x, y = -w / 2, RY + gap
        elif s == "right":
            x, y = RX + gap, -h / 2
        else:
            # 斜角（rt/lt/rb/lb）：把站名的"近角"放在 45° 方向上，
            # 距离仍是 半宽/半高 + gap —— 所以字不会压在药丸上，只是挪到斜对面。
            dx = (RX + gap) * 0.7071
            dy = (RY + gap) * 0.7071
            if s == "rt":
                x, y = dx, -dy - h
            elif s == "lt":
                x, y = -dx - w, -dy - h
            elif s == "rb":
                x, y = dx, dy
            else:                      # lb（未知方向也走这里：按左下摆，最不挤）
                x, y = -dx - w, dy
        # ★★ v2.6.39：手动偏移的叠加**必须挪到 ring 外推之后**（见函数末尾），
        #   这里不能提前 return/continue —— 原来写在 ring 判断之前且限定
        #   `ring == 0`，后果是：**被外推(ring>0)的站名拖了纹丝不动**
        #   （用户：「只要是转弯处的文字均不能被拖动」—— 转弯处线路最密，
        #    站名正是被推到外圈的那一批）。外推量是排版器算的 step，
        #   用户拖的量跟它是两码事，必须**无条件叠加**。
        if ring > 0:
            # ★ v2.6.26：沿该方向再往外让 ring 个"自身框 + 两个间距"。
            #   排版器先试原位（ring=0），找不到干净位置才退到外圈 ——
            #   所以站名平时还是紧贴圆点，只有被线路挡住时才让开。
            # ★★ v2.6.27：外推量**封顶** LABEL_RING_MAX_PX 个屏幕像素。
            #   不封顶的话小档时"一个框宽"在屏幕上也有 53px，而那时站距才
            #   45~70px ⇒ 让 1 圈就骑到隔壁站头上（用户：「文字完全偏离正确位置」）。
            #   ls 就是"屏幕像素 → item 单位"的换算（w = lb.width() * ls）。
            step = min(max(w, h) + gap * 2,
                       # ★ v2.6.42：外推封顶也改成**场景单位**（去掉 × ls）。
                       #   × ls 那版是"屏幕上恒定 60px"，缩放时外推距离不跟图走。
                       LABEL_RING_MAX_SCENE,
                       # ★★ v2.6.54：这一项**本来就是场景单位**（定义处写着
                       #   "≈ 半个站距（场景单位）"）。旧写法 `* _vs * ls` 只有在
                       #   ls == 1/s 时才正好等于它本身 —— v2.6.54 把 ls 改成
                       #   "由目标框宽反推"之后不再成立 ⇒ 外推量随倍率变，
                       #   被外推的站（换乘站居多）换个倍率就漂（实测 37 场景单位）。
                       LABEL_RING_SPAN) * ring
            if s == "left":
                x -= step
            elif s == "right":
                x += step
            elif s == "top":
                y -= step
            elif s == "bottom":
                y += step
            elif s == "rt":
                x += step * 0.7071
                y -= step * 0.7071
            elif s == "lt":
                x -= step * 0.7071
                y -= step * 0.7071
            elif s == "rb":
                x += step * 0.7071
                y += step * 0.7071
            else:
                x -= step * 0.7071
                y += step * 0.7071
        # ★★ v2.6.39：手动拖出来的偏移（屏幕像素 → item 单位要 × k），
        #   **放在最后、无条件叠加**（不管当前是第几圈）。
        #   ★ 别再挪回 ring 判断之前：那样 ring>0 的站名拖了不会动。
        if (self._label_off.x() or self._label_off.y()) and (
                ring == 0 or LABEL_OFF_ALL_RINGS):
            # ★★ v2.6.40：偏移是**场景单位**，直接加，不要再 × k。
            #   （× k 那套是"屏幕像素"时代的写法，跟等比站名不是一把尺子。）
            _kk = 1.0 if LABEL_OFF_SCENE else k
            x += self._label_off.x() * _kk
            y += self._label_off.y() * _kk
        return QRectF(x, y, w, h)

    def label_scene_rect(self, side: Optional[str] = None) -> QRectF:
        """站名在场景坐标中的矩形（供 MapView 做防重叠排版）。"""
        box = self._label_box(side)
        p = self.pos()
        return QRectF(p.x() + box.left(), p.y() + box.top(), box.width(), box.height())

    def set_label_side(self, side: str) -> None:
        # ★★ prepareGeometryChange() 必须【先于】一切会改变 boundingRect() 的动作。
        #    boundingRect() 依赖 _label_side（见 _label_box），所以下面那句
        #    "_label_side = side" 一旦先执行，Qt 就会拿着**新矩形**去索引里
        #    找**旧矩形**插进去的那个节点 —— 找不到，节点就留在 BSP 树里变成
        #    僵尸项；等这个图元被删除（保存/导入会重建全部 379 个站点图元），
        #    索引里剩下的就是野指针，下一次重绘（哪怕场景已空）一遍历就
        #    "Windows fatal exception: access violation" 直接崩。
        self._sprite = None
        # ★ v2.6.26：side 可以带圈数（'right2'），校验的是**去掉圈数后**的基础方向。
        if split_label_ring(side)[0] not in LABEL_SIDES or side == self._label_side:
            if side == self._label_side:
                self._layout_label()
                return
            side = "right"
        self.prepareGeometryChange()
        self._label_side = side
        self._layout_label()
        self.update()

    # ---------- v2.6.32：站名单独拖动 ----------
    def label_off(self) -> QPointF:
        """站名相对"自动摆位"的偏移。

        ★★ v2.6.40：单位是**场景单位**（原来写的是屏幕像素）。跟着 v2.6.38
           "整图等比"一起改的 —— 站名框现在 = 30×scale，偏移若还是屏幕恒定，
           缩放时字相对**地图**就会跑（缩小时被推远、放大时贴回圆点压线）。
           ★ 老数据（label_dx/dy）沿用同一个字段，数值不变、解释变了：
             以前拖过位置的站，改版后会往圆点方向收一点，需要微调一次。
        """
        return self._label_off

    def has_label_off(self) -> bool:
        return (abs(self._label_off.x()) > 0.01
                or abs(self._label_off.y()) > 0.01)

    def set_label_off(self, dx: float, dy: float) -> None:
        """拖动站名时调用：改偏移 + 写回 data（不落盘，落盘由主窗口负责）。"""
        dx, dy = float(dx), float(dy)
        if (abs(dx - self._label_off.x()) < 0.01
                and abs(dy - self._label_off.y()) < 0.01):
            return
        self.prepareGeometryChange()      # ★ boundingRect 含 _label_box
        self._label_off = QPointF(dx, dy)
        self.data["label_dx"] = round(dx, 1)
        self.data["label_dy"] = round(dy, 1)
        self._layout_label()
        self.update()

    def boundingRect(self) -> QRectF:
        # 半径要覆盖悬停光晕（radius + 5*k），否则离屏缓存会把光晕裁掉
        r = self.radius() + 6 * self.text_scale_factor()
        base = QRectF(-r, -r, r * 2, r * 2)
        out = base.united(self._label_box()).adjusted(-1, -1, 1, 1)
        # ★ v2.6.65：胶囊中心偏移（福田口岸横向胶囊跨双站体）——radius() 是
        #   以站坐标为心的圆，罩不住平移后的胶囊 ⇒ 单独把胶囊 AABB（含光晕
        #   余量）并进来，不然离屏缓存裁掉胶囊右半截、鼠标也点不中。
        if self.is_transfer and (self._pill_dx or self._pill_dy):
            k = self.text_scale_factor()
            rx, ry = self.screen_half()          # 屏幕像素，已含偏移
            m = (2 * self.pill_border_screen() + 6) * k   # 光晕余量（同上）
            out = out.united(QRectF(-rx * k - m, -ry * k - m,
                                    2 * (rx * k + m), 2 * (ry * k + m)))
        return out

    def apply_view_scale(self, scale: float) -> None:
        """缩放变化时调用：更新圆点尺寸与字体，保证屏幕视觉大小符合设计。"""
        # ★★ 同 set_label_side：先声明几何要变，再动 _view_scale / 字体 / 标签缩放。
        #    这三者全都进 boundingRect()（radius / text_scale_factor / label_scale）。
        self.prepareGeometryChange()
        self._view_scale = max(scale, 0.01)

        # ★★ 站名字号的正确做法（v2.5.4 重写，修「放大后文字反而变小」）
        #   旧做法：把屏幕字号换算成**整数**场景字号
        #       px = round(screen_font_px / scale)      # QFont 只收整数
        #       实际屏幕字号 = px * scale               # ← 取整误差被缩放原样放大
        #   scale=5 时 round(12/5)=2 → 实际 10px（本该 12px，少 17%）；
        #   scale=3.5 → 3*3.5 = 10.5px；scale=4.5 → 13.5px。
        #   于是从 4.5 倍滚到 5 倍，字反而**缩小 26%**。
        #   而且 Qt 的字形轮廓本身就只认整数像素（实测轮廓高度 = 0.9677×pixelSize，
        #   setPointSizeF(4.2) 与 (4.8) 出来的轮廓完全一样）—— 所以"调小数号"
        #   这条路是死的。
        #
        #   现在：给标签图元自己加一个 1/scale 的缩放，让
        #       【标签局部单位 == 屏幕像素】（view 的缩放正好被抵消）
        #   于是字号 = round(屏幕字号) —— 误差最多 0.5px，且随放大**单调不减**。
        #   副作用有两个，都是好的：
        #     · HaloLabel 的文字路径只在字号跨整数时才重建（以前每缩放一步都作废）；
        #     · 描边宽度直接就是屏幕像素，不用再乘 k。
        want = self.screen_font_px()          # 理论屏幕字号（可能带小数）
        px = max(1, int(round(want)))
        # ★ v2.6.69：站名前置图标标签（多组）—— 尺寸跟字号（1.2×字号），
        #   随缩放一起走（"照片缩放"的一把尺子：图标也是"场景恒定量"）。
        #   set_tags 内部带签名比对，内容没变直接早退，不会炸缓存。
        #   ★ v2.6.75：先过"类别/等级可见性"这道闸（右上角开关面板控制）。
        self.label.set_tags(filtered_tags(self.data.get("tags") or []), px * 1.2)
        f = self.label.font()
        if f.pixelSize() != px:
            f = QFont("Microsoft YaHei")
            f.setPixelSize(px)
            f.setBold(True)                  # ★ 站名加粗
            self.label.setFont(f)
        ls = self.text_scale_factor()
        # ★★ v2.6.43：**补偿字号取整**，让字框的【场景】尺寸严格恒定。
        #   QFont 只收整数像素 ⇒ 0.15 档理论 4.5px 被取成 4px（-11%），
        #   3.0 档 90px 不取整 ⇒ 同一个字在两档的"场景尺寸"差 11%
        #   ⇒ 框中心相对站点漂移（实测跨档 7.5 × 11 场景单位，放大到 3.0 档
        #   就是屏幕上 22~33px 的错位 —— 用户：「低倍率设的位置，高倍率错位」）。
        #   QFont 轮廓只认整数像素（调小数号无效）⇒ 反过来把标签的 1/scale
        #   乘上 want/px 补回来：场景尺寸 = px × ls = want × (1/s) = 恒定。
        if FONT_PROPORTIONAL and px > 0:
            if LABEL_BOX_LOCK and self._ref_ratio > 0.0:
                # ★★ v2.6.54：**直接由"目标场景宽度"反推** ls，不再走
                #   "局部单位 = 屏幕像素（1/s）"那条路 —— 那条路假设字宽 ∝ 字号，
                #   补不了 hinting（实测小档字框胖 55%）。
                #     目标场景宽 = 尺子(ref_ratio) × 场景字号(want/s)  ← 恒定量
                #     ls = 目标 / 实测局部宽
                #   ⇒ 字框场景宽 = 实测局部宽 × ls = 目标 = **跨档恒定**。
                fscene = want / max(self._view_scale, 1e-6)
                target = self._ref_ratio * fscene
                cur = text_advance_at(self._display_name(), px)
                if cur > 1e-6 and target > 1e-6:
                    ls = target / cur
                    self._box_w = target          # ★ 排版框直接用这个恒定量
                else:
                    ls *= want / px
                    self._box_w = 0.0
            else:
                ls *= want / px
        if abs(ls - self._label_ls) > 1e-12:
            # 缩放没变就别 setScale：它会动图元的 transform（进而作废场景索引
            # 与离屏缓存）。收尾时 379 个站点里大部分其实是同一个 ls。
            self._label_ls = ls
            self.label.setScale(ls)          # ★ 局部单位 = 屏幕像素
        # ★ set_halo_width 内部自己会 prepareGeometryChange（见 HaloLabel）
        # ★★ v2.6.38：等比模式下描边也得**跟图走** —— 不然缩小时字变小、
        #   描边不变（还是 2.2 屏幕px）⇒ 站名在场景里反而"变胖"，
        #   字和线的比例关系又对不上了（照片缩放里描边是一起缩的）。
        #   只留 1.0px 的物理下限，免得描边细到渲染不出来。
        if FONT_PROPORTIONAL:
            _halo = max(LABEL_HALO_PX * self._view_scale, 1.0)
        else:
            _halo = LABEL_HALO_PX                 # 已是屏幕像素，不用再换算
        # ★ v2.6.54：`set_halo_width` 收的是**标签局部单位**。上面 ls 已经不再是
        #   1/s（局部单位 ≠ 屏幕像素了）⇒ 要把"想要的屏幕像素"换算回局部单位，
        #   否则描边粗细会跟着 ls 一起被缩放（小档变粗、大档变细）。
        if LABEL_BOX_LOCK:
            _halo = _halo / max(ls * self._view_scale, 1e-6)
        self.label.set_halo_width(_halo)

        # ★ 不在这里作废 sprite：sprite 只由【屏幕量】决定，缩放多数情况下
        #   不改变这些量 → 保留旧 sprite，由 sprite_stale()/render_sprite()
        #   按签名判断是否真的需要重建（避免每次收尾 379 个全量重建 = 750ms）。
        #   （几何声明已在函数开头做过，这里不要再重复调一次）
        self._layout_label()
        # ★ 缓存策略：DeviceCoordinateCache（屏幕坐标位图）。
        #   曾试过 ItemCoordinateCache（纹理化，配合 QOpenGLWidget 做
        #   "只变矩阵"的图片缩放模型），实测纹理尺寸换算与绘制映射对不上：
        #   缩小后圆点整批消失、站名缩成小黑点/错位 —— 已废弃。
        #   现在缩放期间的流畅由 MapView 的"快照拉伸动画"保证，
        #   静止画面的清晰精准由本缓存保证。
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.label.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.update()

    def _layout_label(self) -> None:
        box = self._label_box()
        lb = self.label.boundingRect()
        ls = self.label_scale()
        # box 是"视觉包围盒"的目标位置；boundingRect 自带描边余量，需要抵消
        # ★ 注意 lb 是标签局部坐标，要乘 ls 才是 item 坐标
        self.label.setPos(box.left() - lb.left() * ls, box.top() - lb.top() * ls)

    # ---------- 绘制 ----------
    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        r = self.radius()
        k = self.text_scale_factor()   # 场景 → 屏幕英寸换算

        # ★ v2.6.20：药丸的方向/长度都从 data 里的实测值来（见 pill_half / screen_half）
        #   ★ pill_half() 给的是**白心**尺寸，那圈黑描边只有绘制时才补（+半条描边厚）
        b = self.pill_border_screen() * 0.5
        # ★ v2.7.11：选中时的"红"由 **红环** 负责（下面单独画），这里只留 hover 光晕
        if (self._hover or self._blink) and not self._selected:
            glow = QColor(self._color)
            glow.setAlpha(70)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(glow))
            # ★ 光晕要**跟着药丸方向转**：用轴对齐包围盒画椭圆，斜药丸上会歪出 4 个角
            # ★ 光晕要画在**外廓之外**，所以 = 白心 + 整条描边 + 4px 余量
            hw, hl = self.pill_half()
            painter.save()
            # ★ v2.6.65：胶囊中心偏移（福田口岸横向胶囊）——先平移再旋转
            if self._pill_dx or self._pill_dy:
                painter.translate(self._pill_dx, self._pill_dy)
            painter.rotate(self._pill_ang - 90.0)
            painter.drawEllipse(QPointF(0, 0),
                                (hw + 2 * b) * k + 4 * k,
                                (hl + 2 * b) * k + 4 * k)
            painter.restore()

        if self.is_transfer:
            # ★ 药丸的长轴在「药丸局部坐标」里是竖直的，所以按 (ang − 90) 旋转
            hw, hl = self.pill_half()
            painter.save()
            # ★ v2.6.65：胶囊中心偏移——先平移（item 坐标 = 场景单位）再旋转
            if self._pill_dx or self._pill_dy:
                painter.translate(self._pill_dx, self._pill_dy)
            painter.rotate(self._pill_ang - 90.0)
            self._paint_transfer_pill(painter, (hw + b) * k, (hl + b) * k, k,
                                      fill=(SELECTED_FILL if self._selected else None))
            painter.restore()
        else:
            if self._selected:
                # ★ v2.7.10：选中 ⇒ **整个圆点填成红色**（不再是白心 + 线路色边）
                painter.setBrush(QBrush(QColor(SELECTED_FILL)))
                pen = QPen(QColor(SELECTED_EDGE))
            else:
                # 普通站：白底 + 线路色描边
                painter.setBrush(QBrush(QColor("#FFFFFF")))
                pen = QPen(self._color)
            # 场景单位：× s 才是屏幕像素；k = 1/s 那套是屏幕恒定（v2.6.43 起不用）
            pen.setWidthF(max(SCENE_DOT_STROKE, DOT_STROKE_MIN_PX * k))
            painter.setPen(pen)
            painter.drawEllipse(QPointF(0, 0), r, r)

        # ★ v2.7.11：选中站点的**红色圆环**（画在最外层，亮/灭由 _blink 控制）
        self._paint_selected_ring(painter, k)

    def _paint_selected_ring(self, painter: QPainter, k: float) -> None:
        """选中站点外面那圈**会闪的红色圆环**（v2.7.11）。

        ★ 用户原话：「改为红色圈闪烁，文字不闪烁」+ 点选确认"圆点仍填红"。
          ⇒ 圆点保持红填充（v2.7.10 那版不变），**另加一圈红色圆环**；
            闪烁 = 这圈环亮/灭（`_blink` 为 True 时**不画**环）；
            站名文字完全不动（不改色、不改透明度）。
        ★ 环画在**外廓之外**（圆点半径 + 间隙），这样红点本身不会被环糊住。
        ★ 换乘站的药丸也要跟着方向转 —— 和光晕同一套做法，否则斜药丸上环会歪。
        """
        if not self._selected:
            return
        if self._blink:          # 闪烁的"灭"半周：环不画
            return
        off = RING_OFF_PX * k
        pen = QPen(QColor(SELECTED_FILL))
        pen.setWidthF(max(1.0, RING_W_PX * k))
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if not self.is_transfer:
            r = self.radius() + off
            painter.drawEllipse(QPointF(0, 0), r, r)
            return
        hw, hl = self.pill_half()
        b = self.pill_border_screen() * 0.5
        painter.save()
        if self._pill_dx or self._pill_dy:
            painter.translate(self._pill_dx, self._pill_dy)
        painter.rotate(self._pill_ang - 90.0)
        rx = (hw + b) * k + off
        ry = (hl + b) * k + off
        painter.drawRoundedRect(QRectF(-rx, -ry, rx * 2, ry * 2), rx, rx)
        painter.restore()

    def draw_glyph_screen(self, painter: QPainter, cx: float, cy: float,
                          scale: float) -> None:
        """在**屏幕坐标** (cx,cy) 上实时画这个站的圆点/药丸。

        ★★ v2.6.31（用户原话「先缩小再放大；先放大再缩小」的根治）：
          缩放动画期间站点图元是隐藏的、改画预渲染 sprite，而 sprite 每帧只
          允许重建 6 个（379 个站刷不过来）⇒ 圆点被**冻结**在手势起点的尺寸，
          松手那一步才一次性跳到新尺寸（实测 0.45→1.067：5.21px → 11.76px）。
          圆点是简单几何（圆 / 圆角矩形），矢量画很便宜 ⇒ 合成帧直接按
          **当前虚拟缩放**现算现画，尺寸连续，收尾零跳变。
          文字仍然走 sprite（它的屏幕尺寸只跟字号走，差 16%，冻住可接受）。

        ★ 与 paint() 的关系：paint() 画在 item 局部坐标、靠 Qt 的视图变换放大；
          这里画在屏幕像素坐标，所以要先 translate 到站点、再 scale(s) 把
          "1 单位 = s 屏幕像素"（= 场景单位），好直接复用 _paint_transfer_pill。
        ★ 不画 hover/选中光晕：缩放手势期间不会有 hover 变化，画了反而要同步两套。
        """
        s = max(scale, 0.01)
        if not self.is_transfer:
            r = normal_dot_screen_r(s)
            # ★ v2.7.10：缩放期间画的这版也要跟着红，否则"选中=红"在手势里会闪回白色
            painter.setBrush(QBrush(QColor(SELECTED_FILL if self._selected
                                           else "#FFFFFF")))
            pen = QPen(QColor(SELECTED_EDGE if self._selected else self._color))
            pen.setWidthF(max(SCENE_DOT_STROKE * s, DOT_STROKE_MIN_PX))
            painter.setPen(pen)
            painter.drawEllipse(QPointF(cx, cy), r, r)
            # ★ v2.7.11：缩放期间也要有那圈红环（否则手势里红环会消失一下）
            if self._selected and not self._blink:
                rp = QPen(QColor(SELECTED_FILL))
                rp.setWidthF(max(1.0, RING_W_PX))
                painter.setPen(rp)
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(cx, cy), r + RING_OFF_PX, r + RING_OFF_PX)
            return
        hw, hl = self.pill_half(s)
        b = self.pill_border_screen(s) * 0.5
        painter.save()
        # ★ v2.6.65：胶囊中心偏移（场景单位 → 屏幕 ×s），先平移再旋转
        painter.translate(cx + self._pill_dx * s, cy + self._pill_dy * s)
        painter.rotate(self._pill_ang - 90.0)
        painter.scale(s, s)          # 屏幕像素 → 场景单位
        self._paint_transfer_pill(painter, (hw + b) / s, (hl + b) / s, 1.0 / s,
                                  fill=(SELECTED_FILL if self._selected else None))
        if self._selected and not self._blink:
            rp = QPen(QColor(SELECTED_FILL))
            rp.setWidthF(max(1.0, RING_W_PX * s))
            painter.setPen(rp)
            painter.setBrush(Qt.NoBrush)
            rx = (hw + b) + RING_OFF_PX * s
            ry = (hl + b) + RING_OFF_PX * s
            painter.drawRoundedRect(QRectF(-rx, -ry, rx * 2, ry * 2), rx, rx)
        painter.restore()

    def _paint_transfer_pill(self, painter: QPainter, RX: float, RY: float,
                             k: float, fill: Optional[str] = None) -> None:
        """换乘站图标：**白色胶囊（大药丸）**，照原图画法。

        ★ 调用方已经把画布旋转到药丸自身方向（长轴 = 局部 Y 轴），
          所以这里只要按 (RX=半宽, RY=半长) 画即可，不用管横竖斜。

        ★ v2.6.19：用户原话「我就喜欢大药丸的换乘样式，请使用这种方式」。
          原图实测：普通站是 22×22 正圆；换乘站是 25×48 胶囊，白色填充 +
          深色描边；多线换乘被撑长到 25×74 / 25×112 / 25×138。
        ★ v2.6.20：方向与长度改为逐站实测（横 13 / 竖 43 / 斜 12）。
        ★ v2.6.20 补：描边改成**跟原图一样粗的黑边**。调用方传进来的 RX/RY 是
          **描边环的中线**半径，这里用 TRANSFER_PILL_BORDER 宽的笔描上去，
          笔心在中线上 ⇒ 覆盖 [白心/2, 白心/2+BORDER]，白心正好 26、外廓 41。
          第一版只用了 SCREEN_DOT_STROKE(1.9) 的细笔 ⇒ 药丸瘦一圈（26 vs 41）。
        ★ 取代 v2.6.11 的「🔄 旋转箭头环」（用户不再要那个）。
        ★ 中心留一个线路色小圆点：换乘站压在多条线上，用它表明主色。
        """
        # ① 白底胶囊：压在彩色线路上时不会和线条糊在一起
        #    圆角半径 = 半宽 ⇒ 两端是正圆头（胶囊），不是方角矩形
        #    ★ v2.7.10：`fill` 非 None（选中态）⇒ 整个胶囊填成那个颜色（红色），
        #      白心也一起红 —— 用户选的就是"整个圆点填成红色"。
        rect = QRectF(-RX, -RY, RX * 2, RY * 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(fill or "#FFFFFF")))
        painter.drawRoundedRect(rect, RX, RX)

        # ② 深色描边（★ 按原图实测的 7 场景单位，笔心压在描边环中线上）
        pen = QPen(QColor(SELECTED_EDGE if fill else TRANSFER_RING_COLOR))
        pen.setWidthF(TRANSFER_PILL_BORDER)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, RX, RX)

        # ③ 中心：线路色实心圆点
        if fill:
            # ★ v2.7.10：选中态**不画中心点** —— 用户选的是"整个圆点纯红"，
            #   红底上留一个白/线路色的小点看着像没填满。
            return
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._color))
        cr = SCREEN_NORMAL_R * 0.62 * k
        painter.drawEllipse(QPointF(0, 0), cr, cr)

    @staticmethod
    def _draw_arc_arrow(painter: QPainter, ring_r: float, deg: float,
                        k: float) -> None:
        """在弧的**末端**画一个实心三角箭头，指向该点的切线（逆时针前进）方向。

        ★★ 顶点一律走 `transfer_arrow_points()`（沿**弧**布置），别在这里另算：
           v2.6.11 第一版在这儿"沿切线后退 L"当底边，结果底边到圆心的距离是
           `sqrt(ring_r²+L²)` = **5.37px > 白底圆 5.20px** ⇒ 箭头整块飞到圆外，
           回归采样取到的是背景色。
        ★ `k` 是「屏幕像素 → 场景单位」的换算（`ring_r` 已经是场景单位了，
          所以只有 `SCREEN_*` 那两个常量需要乘 `k`）。
        """
        pts = transfer_arrow_points(ring_r, deg,
                                    SCREEN_TRANSFER_ARROW_W * k,
                                    TRANSFER_ARROW_RING_OFF * k)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(TRANSFER_RING_COLOR)))
        painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))

    # ---------- sprite（缩放动画贴图） ----------
    def _sprite_sig_key(self, dpr: float):
        """sprite 内容签名（只含决定像素的屏幕量）。返回 None = 不可渲染。

        ★ 关键：所有量都换算到【屏幕像素】后再量化 —— 场景量随缩放变化，
        但屏幕量不变，因此同一视觉结果在不同缩放下签名相同、无需重建。
        """
        # ★ v2.6.31：sprite 只烤**站名文字**（圆点改由 draw_glyph_screen 矢量画），
        #   所以签名按标签尺寸算，别再拿 boundingRect（那会把圆点算进去）。
        lb = self.label.boundingRect()
        w = lb.width() + 2.0 * LABEL_SPRITE_PAD
        h = lb.height() + 2.0 * LABEL_SPRITE_PAD
        if w <= 1 or h <= 1 or w > 800 or h > 400:
            return None
        f = self.label.font()
        ls = self.label_scale()

        def q(v: float) -> float:
            """量化到 0.5px 档：视觉不可辨，但能让"缩放中每帧都在变"的
            连续量变成少量离散档位 → sprite 只在真正跨档时重建。"""
            return round(v * 2.0) / 2.0

        return (
            round(max(1.0, dpr), 2),
            int(round(w)), int(round(h)),
            bool(self._label_on),
            q(self.label.pos().x() * self._view_scale),   # 标签屏幕偏移
            q(self.label.pos().y() * self._view_scale),
            # ★★ 用**真实字号**（font().pixelSize()）而不是"想要的屏幕字号"：
            #   实际呈现的字号是 round(想要的)，两者在 D=n+0.5 处差 1px，而
            #   q(D) 的档位边界在 D=n+0.25 —— 边界不重合，就会出现
            #   "签名没变、字号其实变了"的空档（sprite 会留一帧旧字号）。
            #   实测这次没被肉眼抓到，是因为签名里还有 int(round(w/h))（标签框
            #   宽高随字号变）顺手兜住了 —— 但那是**碰巧**，不是设计。
            #   现在直接钉住真实字号，依赖关系是显式的，拆掉兜底也不会坏。
            int(f.pixelSize()),
            # ★ 描边是标签局部量：× label_scale() × view_scale 才是屏幕像素
            q(self.label.halo_width() * ls * self._view_scale),
            f.bold(), self.label.text(), bool(self.is_transfer),
            # ★ v2.6.20：药丸方向/长度也要进签名 —— 45° 与 135° 的包围盒完全相同，
            #   只看 w/h 会漏判（切到另一个斜向时 sprite 不重建）。
            q(self._pill_ang),
            bool(self._hover), bool(self._selected),
        )

    def sprite_stale(self, dpr: Optional[float] = None) -> bool:
        """当前 sprite 是否与目标状态不符（需要重建）。开销 ~µs，可放心调用。"""
        d = self.devicePixelRatioF() if dpr is None else dpr
        if self._sprite is None:
            # ★ v2.6.31：`_sprite` 为 None 有两种含义 ——
            #   ① 还没烤过（_sprite_sig 也是 None）⇒ 该烤；
            #   ② 站名当前不显示，**有意**不烤（签名已记下）⇒ 别每帧重建。
            pass
        return self._sprite_sig != self._sprite_sig_key(d)

    def render_sprite(self, dpr: float = 1.0) -> None:
        """把**站名文字**渲染成透明底小图，缓存到 self._sprite。

        ★★ v2.6.31：**不再烤圆点/药丸**。为什么：圆点是"跟场景"的（半径 =
          原图 11 × 缩放），而 sprite 在缩放动画期间是**冻结**的（每帧只允许
          重建 6 个，379 个站刷不过来）⇒ 圆点全程停在手势起点的尺寸，松手那
          一步才一次性跳到新尺寸 —— 就是用户说的「先缩小再放大 / 先放大再缩小」
          （实测 0.45→1.067：圆点 5.21px 冻结 → 收尾 11.76px，跳 2.26 倍）。
          现在圆点由 draw_glyph_screen() 在合成帧里矢量实时画（尺寸连续）；
          文字的屏幕尺寸只跟字号走（12.99→15.09，差 16%），冻住可以接受。

        ★ sprite 尺寸 = 屏幕呈现尺寸（本设计下图元屏幕尺寸恒定），因此
        缩放动画中 sprite 按屏幕坐标原样贴图即可 —— 文字/圆点不随缩放
        拉伸变形，始终清晰（Google 地图 marker 的做法）。
        必须在几何定稿（apply_view_scale 之后）调用。
        签名未变则直接复用现成 sprite（绝大多数缩放收尾走这条路，0 开销）。
        """
        sig = self._sprite_sig_key(dpr)
        # 站名当前不显示 ⇒ 有意不烤（但把签名记下来，免得每帧重建）
        if sig is None or not self._label_on:
            self._sprite = None
            self._sprite_sig = sig
            return
        if self._sprite is not None and self._sprite_sig == sig:
            return
        self._sprite = None
        self._sprite_sig = None
        lb = self.label.boundingRect()
        # 标签局部 1 单位 == 1 屏幕像素（见 label_scale）⇒ 直接拿它的宽高
        w = lb.width() + 2.0 * LABEL_SPRITE_PAD
        h = lb.height() + 2.0 * LABEL_SPRITE_PAD
        d = max(1.0, dpr)
        pm = QPixmap(max(2, math.ceil(w * d)), max(2, math.ceil(h * d)))
        pm.setDevicePixelRatio(d)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        lp = self.label.pos()
        # ★ pixmap 设过 setDevicePixelRatio(d) ⇒ painter 坐标是**逻辑像素**，
        #   不要再乘 d（乘了文字就被画成 1.5 倍大 —— 实测小档整幅差异 4% → 7.7%）。
        p.scale(self._view_scale, self._view_scale)
        p.translate(-lp.x() + LABEL_SPRITE_PAD / self._view_scale,
                    -lp.y() + LABEL_SPRITE_PAD / self._view_scale)
        opt = QStyleOptionGraphicsItem()
        # ★ 注意用 _label_on 标志而非 label.isVisible()：
        #   isVisible() 含父级可见性 —— 动画期间站点图元整体隐藏（父级 hidden），
        #   此时按需重建的 sprite 会全部丢失站名文字，收尾又恢复 —— 表现为
        #   "文字显示异常后恢复正常"
        if self._label_on:
            # ★ 必须补上标签自己的缩放：这里是手工画（不走场景图），
            #   QGraphicsItem 自身的 transform 不会被自动带上。
            #   少了这一步，站名会按"局部单位"贴出去 —— 即被缩小 1/scale 倍。
            ls = self.label_scale()
            p.translate(self.label.pos())
            if ls != 1.0:
                p.scale(ls, ls)
            self.label.paint(p, opt, None)
        p.end()
        # 圆点中心（item 场景坐标 0,0）在 sprite 内的逻辑像素位置
        # ★ 第 4 项 = 这张 sprite 是**按哪个缩放**烤的：合成帧要按它把文字
        #   缩放到当前虚拟缩放的字号（否则字号也冻住，收尾再跳一下）。
        self._sprite = (pm,
                        -lp.x() * self._view_scale + LABEL_SPRITE_PAD,
                        -lp.y() * self._view_scale + LABEL_SPRITE_PAD,
                        self._view_scale)
        self._sprite_sig = sig

    def invalidate_sprite(self) -> None:
        self._sprite = None
        self._sprite_sig = None

    # ---------- 标签 ----------
    def _display_name(self) -> str:
        return self.data.get("station_name", "")

    def set_label_visible(self, on: bool) -> None:
        if on == self._label_on:
            return
        self._sprite = None
        self._label_on = on
        self.label.setVisible(on)

    def is_label_visible(self) -> bool:
        return self._label_on

    def update_from_data(self, data: Dict) -> None:
        # ★★ 同样：is_transfer 决定 radius()、setText 决定标签尺寸，
        #    两者都进 boundingRect() → 必须先声明几何要变再改。
        self.prepareGeometryChange()
        self.data = dict(self.data, **data)
        self._sprite = None
        self.is_transfer = bool(self.data.get("is_transfer"))
        name = self._display_name()
        if name != self.label.text():
            self.label.setText(name)
        # ★ v2.6.69：标签内容变了就重排（尺寸沿用当前的，下一次缩放会重算）。
        #   set_tags 自带签名比对：没变就早退，不会白白炸缓存。
        #   ★ v2.6.75：先过"类别/等级可见性"这道闸（右上角开关面板控制）。
        self.label.set_tags(
            filtered_tags(self.data.get("tags") or []),
            self.label._tag_px if self.label._tag_px > 0 else 24.0,
        )
        self._layout_label()
        self.update()

    # ---------- 交互 ----------
    def _notify_label(self) -> None:
        """通知视图重新评估本站名是否显示（悬浮/取消悬浮时）。"""
        sc = self.scene()
        if not sc:
            return
        for v in sc.views():
            fn = getattr(v, "_apply_label_visible", None)
            if callable(fn):
                fn(self)

    def hoverEnterEvent(self, event):
        # ★★ _hover 让 radius() 变大（screen_radius 里 +2）→ 先声明再改
        self.prepareGeometryChange()
        self._sprite = None
        self._hover = True
        self._layout_label()
        self.update()
        self._notify_label()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.prepareGeometryChange()
        self._sprite = None
        self._hover = False
        self._layout_label()
        self.update()
        QToolTip.hideText()               # ★ v2.6.70：离开时收掉图标 tooltip
        self._notify_label()
        super().hoverLeaveEvent(event)

    # ---------- 图标悬浮提示（v2.6.70）----------
    def _tag_text_at(self, item_pos) -> str:
        """光标（item 坐标）压在哪个图标上 → 返回该组记录的文字；没压到返回 ''。"""
        lab = getattr(self, "label", None)
        if lab is None or not getattr(lab, "_tags", None):
            return ""
        p = lab.mapFromItem(self, QPointF(item_pos))   # 标签局部坐标
        icon_rects, _xs, _nx = lab._layout_cached()
        for (_ic, tx, _pos), ir in zip(lab._tags, icon_rects):
            if tx and not ir.isNull() and ir.contains(p):
                return tx
        return ""

    def hoverMoveEvent(self, event):
        # ★ v2.6.70：悬浮在主图图标上 → 显示该图标记录的文字（xx酒店/xx商场）。
        #   文字为空的组（如纯 🚄）不弹。
        # ★★ v2.6.74 修复"悬浮不弹"：Qt6 的 QGraphicsSceneHoverEvent **没有
        #   globalPos()**（Qt5 遗留调用），每次悬浮都在这里抛 AttributeError
        #   被 Qt 吞掉 ⇒ tooltip 永远出不来。改用 Qt6 的 screenPos()（QPoint），
        #   异常时兜底 QCursor.pos()。
        tip = self._tag_text_at(event.pos())
        if tip:
            try:
                gp = event.screenPos()
            except AttributeError:
                from PySide6.QtGui import QCursor
                gp = QCursor.pos()
            QToolTip.showText(gp, tip)
        elif QToolTip.isVisible():
            QToolTip.hideText()
        super().hoverMoveEvent(event)

    def set_selected_visual(self, on: bool) -> None:
        # ★★ _selected 同样进 radius() → 先声明再改
        self.prepareGeometryChange()
        self._sprite = None
        self._selected = on
        # ★ v2.7.11：**站名不跟着变了**（用户：「改为红色圈闪烁，**文字不闪烁**」，
        #   并在点选里确认"文字不变色"）。
        #   ⇒ 选中态的辨识全靠圆点填红 + 外面那圈会闪的红环（见 _paint_selected_ring）。
        #   ★ 这里仍然把字色钉回正常值：从 v2.7.10 升级上来的实例可能还带着红字。
        if self.label is not None:
            self.label.setBrush(QBrush(QColor(LABEL_COLOR_NORMAL)))
        self.update()

    def set_blink(self, on: bool) -> None:
        """★ v2.6.90：定位闪烁开关（MapView.blink_station 的定时器调）。

        ★ v2.7.11：**只闪那圈红环，不再动站名**（用户原话「改为红色圈闪烁，
          文字不闪烁」）。实现上只是翻转 `_blink`，环的亮/灭在
          `_paint_selected_ring` 里判；文字透明度一律钉回 1.0。
        """
        self._blink = bool(on)
        self._sprite = None
        self.label.setOpacity(1.0)
        # ★ v2.7.11：红环的亮/灭是在 paint 里判的 ⇒ **必须主动重绘**，
        #   否则定时器翻 `_blink` 时画面不会动（看着"不闪"）。
        # ★★ v2.7.13：光 update() **不够** —— 本类开着
        #   DeviceCoordinateCache（缩放流畅靠它），实测红环亮/灭两态渲染出来的
        #   像素**一模一样**（680 / 680），即缓存位图没被作废旧；关掉缓存后立刻
        #   出现差异（680 → 507）。⇒ 切一下 cacheMode 强制丢弃旧位图。
        #   只影响"被选中那一个站"，闪烁 4 回合总量可忽略。
        self.setCacheMode(QGraphicsItem.NoCache)
        self.update()
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        # ★ 只记左键：右键是"上下文菜单"，不参与拖动判定。
        #   每次都重写（包括非左键写成 None），避免上一次的残留位置骗到判断。
        self._press_pos = QPointF(self.pos()) if event.button() == Qt.LeftButton else None
        # ★ v2.6.91：跳变否决的基准 = 按下位置（见 itemChange 里 _guard_drag_pos）
        self._drag_last_pos = QPointF(self.pos()) if self._press_pos is not None else None
        # ★ v2.6.88：挪站上报去重标记（view 层确定性收尾 / 图元收尾 二选一）
        self._move_reported = False
        # ★ v2.6.55：左键按下 = 这一次拖动要开吸附（松手即关，见 mouseReleaseEvent）
        #   ★ v2.6.66：**按住 Alt 拖 = 本次不吸附**。用户原话「下梅林站我无法用
        #     手动对齐原图中心」——正确位置离旧走廊只有 12~33px，全在吸附半径
        #     (TRACE_SNAP_R=30) 里，松手前位置永远被吸回旧走廊 ⇒ 拖不到位。
        #     Alt 是"微调/摆脱磁铁"的通用手势：按住 = 自由放置，松开恢复吸附。
        if event.button() == Qt.LeftButton:
            self._snapping = not bool(event.modifiers() & Qt.AltModifier)

    def itemChange(self, change, value):
        """★ v2.6.55（乙）：拖动站点时**吸到官方原图的走廊上**。

        放在 itemChange 里而不是 mouseMoveEvent 里，是因为 Qt 自己搬图元的位置
        —— 在 move 里 setPos 会跟 Qt 的位移计算打架（第二次 move 又从我设的位置
        往外推，变成"越拖越飘"）。itemChange 是**位置真正被写进去之前**的钩子，
        改它返回的值就是改最终位置，谁设的都拦得住。

        ★ v2.6.89：🔒 锁定否决 —— `STATIONS_LOCKED` 为 True 且**正在用鼠标拖**
          （`_press_pos` 非 None，见 mousePressEvent）时，一律把位置按回原地。
          ★ 必须带 `_press_pos` 这道门：程序化 setPos（撤销/重做/重载/对齐）
            不受锁影响，否则 Ctrl+Z 会把站"锁"在旧位置上。
        """
        if (change == QGraphicsItem.ItemPositionChange and STATIONS_LOCKED
                and getattr(self, "_press_pos", None) is not None):
            return self._guard_drag_pos(QPointF(self.pos()))   # 拖动被锁：纹丝不动
        if (change == QGraphicsItem.ItemPositionChange and TRACE_SNAP
                and getattr(self, "_snapping", False)):
            # ★★ 只在**真的在拖**时才吸。不加这道门，【单击一个站点】也会被
            #   吸附拽到走廊上（可能挪十几像素）⇒ mouseReleaseEvent 判定"移动过"
            #    ⇒ 写盘 + 重建 20 条线路 + 把 _updated_at 刷成点击时间。
            #    那正是 v2.5.5 好不容易修掉的"点一下卡一下"（`_chk_click_no_save`
            #    C 组当场抓到：手抖 0.02 场景单位也落盘）。
            #    ★ 门开在**屏幕 6px**（换算成场景 = 6/view_scale）——
            #      用场景常量会在小档变成"几乎不设门"，在大档变成"拖不动"。
            #    ★ `_press_pos` 为 None = 程序化 setPos（不是鼠标拖）⇒ 照吸不误。
            p0 = getattr(self, "_press_pos", None)
            if p0 is not None:
                _vs = max(float(getattr(self, "_view_scale", 1.0) or 1.0), 1e-6)
                if (abs(float(value.x()) - p0.x())
                        + abs(float(value.y()) - p0.y())) * _vs < 6.0:
                    return self._guard_drag_pos(
                        super().itemChange(change, value))
            try:
                from ui import trace_assist as _TA
                s = _TA.snap(self.data.get("lines") or [],
                             float(value.x()), float(value.y()), TRACE_SNAP_R)
                if s is not None:
                    return self._guard_drag_pos(QPointF(s[0], s[1]))
            except Exception:
                pass        # 吸附只是锦上添花，出错就当没这功能，绝不能挡住拖动
        if change == QGraphicsItem.ItemPositionChange:
            return self._guard_drag_pos(super().itemChange(change, value))
        return super().itemChange(change, value)

    def _guard_drag_pos(self, cand) -> "QPointF":
        """★ v2.6.91：拖动"单步跳变否决"（详见模块头 DRAG_JUMP_LIMIT 注释）。

        只在**鼠标拖动中**（_press_pos 非 None）生效：候选位置与上一次接受的
        位置一步差出 DRAG_JUMP_LIMIT 个场景单位以上 ⇒ 判为变换脱节造成的甩飞，
        原地按住不动（宁可"拖不动"也不能"飞出去"）。程序化 setPos（撤销/
        重载/定位）不受任何影响。
        """
        if not isinstance(cand, QPointF):
            return cand
        last = getattr(self, "_drag_last_pos", None)
        if getattr(self, "_press_pos", None) is None or last is None:
            return cand
        if (abs(cand.x() - last.x()) + abs(cand.y() - last.y())) > DRAG_JUMP_LIMIT:
            return QPointF(last)
        self._drag_last_pos = QPointF(cand)
        return cand

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        p = self.pos()
        self.data["x"] = round(p.x(), 1)
        self.data["y"] = round(p.y(), 1)

    def mouseReleaseEvent(self, event):
        self._snapping = False
        self._drag_last_pos = None      # ★ v2.6.91：跳变基准只在一次拖动内有效
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton or not self.scene():
            return
        # ★ v2.6.88：view 层确定性收尾已代为上报（_move_reported）⇒ 不再发一次
        #   （双发 = 双份撤销记录，Ctrl+Z 一下"看起来没反应"）。
        if getattr(self, "_move_reported", False):
            self._move_reported = False
            return
        # ★★ 只有"真的移动过"才通知主窗口落盘（v2.5.5 修）
        #
        # 旧实现是：只要左键松手就 emit，于是【单击选中一个站点】会顺手做完全套：
        #     main_window._on_station_moved → dm.upsert_station + dm.save()
        #         （写 147KB 的 stations.json + 13KB lines.json，还要各备份一份 .bak）
        #         + map_view.rebuild_lines()（重建全部 20 条线路的几何）
        #         + _refresh_status() + 底部提示条写"已移动「X」→ (x, y)"（其实没动）
        #     map_view._on_station_moved_internal → _invalidate_nn()
        #         + _update_label_visibility()（379 站全量防重叠排版，实测 97~109ms）
        #   合计 ≈110~120ms / 每次单击
        # 也就是"点一下卡一下"，而且每次点击都会把该站的 _updated_at 刷成本次点击时间。
        #
        # 真凶现场：tools/verify_anchor_exe.py 往真机窗口里发了两下【点击】，
        # 软件/data/stations.json 里就凭空多出两条 _updated_at（罗湖北 / 福坑），
        # 坐标却一字未改 —— 正是"点了但没动"。
        #
        # 取不到按下位置时（理论上不该发生）按"移动过"处理，保守沿用旧行为。
        p0 = self._press_pos
        self._press_pos = None
        if p0 is not None:
            p1 = self.pos()
            if (abs(p1.x() - p0.x()) < STATION_MOVE_EPS
                    and abs(p1.y() - p0.y()) < STATION_MOVE_EPS):
                return
        views = self.scene().views()
        if views and hasattr(views[0], "station_moved"):
            self._move_reported = True   # ★ v2.6.88：本图元已上报，view 层别再发
            views[0].station_moved.emit(self.station_id)


# ------------------------------------------------------------
# 线路几何索引（v2.6.9）
# ------------------------------------------------------------
# 用户：「站点文字有概率显示在线路线条中，理应在上下左右等其他位置」。
#
# 根因：`MapView._update_label_visibility()` 的防重叠排版只把
#   **站点圆点**当障碍物（`dot` 桶），线路**根本没进障碍表** ⇒
#   站名被放到左右两侧时，如果那条线正好横着穿过站点，站名就整条压在线上。
#   （HaloLabel 的白色描边只是"还看得清"，并不是"不重叠"——用户要的是后者。）
#
# 修法：把线路中心线切成小段，建一个粗网格索引，排版时对每个候选位置问一句
#   "这块矩形压到线没有"，**优先选压不到线的一侧**；八个方向全都压线时才
#   退而求其次（选压得最少的那个），保证站名不会因为避让线路而整片消失。
#
# ★ 为什么不直接 `QPainterPath.intersects(rectPath)`：一次几十微秒，
#   379 站 × 8 方向 × 20 条线 = 6 万次 ⇒ 一秒多，收尾时直接卡死。
#   切成段 + 网格索引后，一次查询只测身边的几条段，实测见 README。

def seg_hits_rect(seg: Tuple[float, float, float, float],
                  rect: QRectF, pad: float) -> bool:
    """线段（场景坐标）与"向外扩了 pad 的矩形"是否相交。

    三步：包围盒粗筛 → 端点是否落在里面 → 与四条边求交（叉积同号法）。
    """
    x1, y1, x2, y2 = seg
    l = rect.left() - pad
    t = rect.top() - pad
    rgt = rect.right() + pad
    b = rect.bottom() + pad
    # ① 包围盒粗筛（绝大多数段在这一步就被否掉）
    if max(x1, x2) < l or min(x1, x2) > rgt:
        return False
    if max(y1, y2) < t or min(y1, y2) > b:
        return False
    # ② 端点落在矩形内
    if l <= x1 <= rgt and t <= y1 <= b:
        return True
    if l <= x2 <= rgt and t <= y2 <= b:
        return True
    # ③ 与四条边求交
    def _o(ax, ay, bx, by, cx, cy):
        v = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        return 1 if v > 0.0 else (-1 if v < 0.0 else 0)

    def _cross(ax, ay, bx, by, cx, cy, dx, dy) -> bool:
        return (_o(ax, ay, bx, by, cx, cy) != _o(ax, ay, bx, by, dx, dy)
                and _o(cx, cy, dx, dy, ax, ay) != _o(cx, cy, dx, dy, bx, by))

    return (_cross(x1, y1, x2, y2, l, t, rgt, t)
            or _cross(x1, y1, x2, y2, rgt, t, rgt, b)
            or _cross(x1, y1, x2, y2, rgt, b, l, b)
            or _cross(x1, y1, x2, y2, l, b, l, t))


def _clip_len(x1: float, y1: float, x2: float, y2: float,
              l: float, t: float, rgt: float, b: float) -> float:
    """线段落在矩形内的那一段有多长（Liang–Barsky 裁剪）。0 = 完全在外面。"""
    dx = x2 - x1
    dy = y2 - y1
    u1, u2 = 0.0, 1.0
    for pi, qi in ((-dx, x1 - l), (dx, rgt - x1), (-dy, y1 - t), (dy, b - y1)):
        if abs(pi) < 1e-12:
            if qi < 0.0:
                return 0.0
            continue
        u = qi / pi
        if pi < 0.0:
            if u > u2:
                return 0.0
            if u > u1:
                u1 = u
        else:
            if u < u1:
                return 0.0
            if u < u2:
                u2 = u
    if u2 <= u1:
        return 0.0
    return (u2 - u1) * math.hypot(dx, dy)


class LineSegIndex:
    """线路中心线的空间索引：问"这块矩形里穿过了多长的线"。

    ★ 索引是**粗网格**（格边长 ≈ 2 个排版格），段按包围盒登记；
      查询时只测矩形覆盖到的那几格里的段 —— 而不是遍历全部几千段。
    ★ `build()` 有版本缓存：线路几何没变、格边长没变就直接复用
      （缩放收尾时排版会跑很多次，几何往往一次都没变）。
    """

    def __init__(self):
        self.segs: List[Tuple[float, float, float, float]] = []
        self.buckets: Dict[tuple, List[int]] = {}
        self.cell = 1.0
        self._version = -1

    def build(self, line_items: Dict[str, "MetroLineItem"],
              cell: float, version: int) -> None:
        if version == self._version and abs(cell - self.cell) < 1e-6:
            return
        segs: List[Tuple[float, float, float, float]] = []
        for it in line_items.values():
            try:
                if not it.isVisible():       # 隔离时只算看得见的那条线
                    continue
                polys = it.path().toSubpathPolygons()
            except Exception:
                continue
            for poly in polys:
                n = poly.count()
                for i in range(n - 1):
                    a = poly.at(i) if hasattr(poly, "at") else poly[i]
                    b = poly.at(i + 1) if hasattr(poly, "at") else poly[i + 1]
                    segs.append((a.x(), a.y(), b.x(), b.y()))
        self.segs = segs
        self.cell = max(float(cell), 1.0)
        c = self.cell
        bk: Dict[tuple, List[int]] = {}
        for idx, (x1, y1, x2, y2) in enumerate(segs):
            cx0 = int(math.floor(min(x1, x2) / c))
            cx1 = int(math.floor(max(x1, x2) / c))
            cy0 = int(math.floor(min(y1, y2) / c))
            cy1 = int(math.floor(max(y1, y2) / c))
            for cx in range(cx0, cx1 + 1):
                for cy in range(cy0, cy1 + 1):
                    key = (cx, cy)
                    lst = bk.get(key)
                    if lst is None:
                        bk[key] = [idx]
                    else:
                        lst.append(idx)
        self.buckets = bk
        self._version = version

    def hit_length(self, rect: QRectF, pad: float) -> float:
        """矩形（外扩 pad 后）里穿过了多长的线路（场景单位）。0 = 完全没碰到。

        ★ 为什么是"长度"而不是"压到几条段"：一条线**擦着站名边角过去**
          和一条线**从站名正中横穿过去**，"段数"都是 1，但后者才是用户抱怨的
          "字融进线条里"。按长度打分才能真正挑出压得最少的那一侧
          （实测缩到最小时：段数法 54.5%→50.2%，长度法 → 更低）。
        """
        if not self.segs:
            return 0.0
        c = self.cell
        l = rect.left() - pad
        t = rect.top() - pad
        rgt = rect.right() + pad
        b = rect.bottom() + pad
        x0 = int(math.floor(l / c))
        x1 = int(math.floor(rgt / c))
        y0 = int(math.floor(t / c))
        y1 = int(math.floor(b / c))
        seen = set()
        total = 0.0
        segs = self.segs
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                lst = self.buckets.get((cx, cy))
                if not lst:
                    continue
                for idx in lst:
                    if idx in seen:
                        continue
                    seen.add(idx)
                    s = segs[idx]
                    total += _clip_len(s[0], s[1], s[2], s[3], l, t, rgt, b)
        return total
