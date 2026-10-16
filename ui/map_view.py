"""
ui/map_view.py
========================
地图视图（核心交互部件）—— 矢量绘制版。

★ 不再贴图片！线路和站点全部由程序根据 data/*.json 绘制：

  ┌ 场景 (QGraphicsScene, 8000×8000) ────────────────────┐
  │  · 背景：浅色纸面                                      │
  │  · 线路层：16 条 MetroLineItem（官方色粗线，平滑曲线）    │
  │  · 站点层：252 个 StationDotItem（白底圆点 + 线色描边）    │
  └──────────────────────────────────────────────────────┘

尺寸策略：圆点/文字/线宽都用屏幕像素定义，按缩放换算成场景坐标，
          因此放大缩小时屏幕视觉大小恒定（与官方地铁图一致）。

交互：
  悬浮 → 圆点放大 + 气泡提示
  单击 → 选中，右侧信息面板
  双击 → 弹窗编辑
  拖动站点 → 移动站点，落盘
  ★ 空白处按下拖动 → 平移地图（也支持按住中键任意位置拖动）
  右键 → 菜单（编辑/放大查看/复制 ID/删除）
  ↑↓←→ → 同方向最近站点
  Enter → 等同双击
  Tab   → 跳到最近站点
  Esc   → 取消选择
  滚轮   → 缩放

站名显隐（v2.1 起 / v2.5.2 加强）：
  不用"缩放级别一刀切隐藏"，而是**贪心防重叠排版**：按优先级依次给每个站名
  找一个不与别人重叠的落点（右→左→上→下→四个斜角，共 8 个方向），
  放得下就显示、放不下才隐藏。缩小时依然"尽可能多"地显示站名。
  v2.5.2 起改成**两轮**：第一轮严格（零重叠，与旧版一致），第二轮把留白收紧
  并允许轻微重叠（≤12% 面积），只为"第一轮没地方站的"站名再争取一次 ——
  实测缩到最小时站名从 102 个提到 245 个（379 站），且没有任何站名被压掉超过一半。
"""

from __future__ import annotations

import json
import math
import os
import sys
import time as _time_mod
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QRect, QRectF, QPoint, QPointF, QSize, QSizeF, Signal, QTimer

_perf = _time_mod.perf_counter
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QKeyEvent, QPixmap,
)
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsPixmapItem, QMenu,
    QMessageBox, QApplication, QLabel,
)

from core.data_manager import get_data_manager
from ui.metro_render import (
    MetroLineItem, StationDotItem, LABEL_SIDES, LABEL_SIDES_CARDINAL, effective_font_px,
    LineSegIndex, SCREEN_LINE_W, line_screen_width, DashedLinkItem,
    LINK_LABEL_SIDES, TerminalBadgeItem, badge_scene_size,
    BADGE_SCENE, BADGE_GAP, BADGE_SPREAD, LABEL_SPRITE_PAD,
    STATION_MOVE_EPS, set_tag_visibility,
)
from ui.map_cursor import cursor as map_cursor   # v2.6.12：自绘的圆环光标
from ui.scale_panel import ScalePanel            # v2.6.41：右上角双滑块
from ui.icon_toggle_panel import IconTogglePanel  # v2.6.75：图标类别/等级开关


def apply_through_links(seq, links) -> List[str]:
    """把「贯通运营」的端点站接到线序上，让两条线画成**一条连续的实线**。

    ★ 用户的场景：2号线到莲塘为止，但**实际和 8号线的梧桐山南是同一列车**
      （8号线自己又没有莲塘站）⇒ 官方原图上这段是连着的，我们原来断成两截。
      用户原话：「你没有把2号线和8号线连在一起？」
                「梧桐山南连按照一条线路那样把它连起来即可」

    ★ 两侧都试（a 在头就把 b 往前插、a 在尾就把 b 往后接），所以
      2号线拿到「…莲塘→梧桐山南」、8号线拿到「莲塘→梧桐山南→…」，
      两条线各画一遍这段，同色叠在一起 = 看起来就是一条线。
    ★ 带了 guard + `not in seq` 双重保护：数据写成环也不会死循环。
    """
    seq = list(seq)
    for _ in range(8):                       # 最多连锁 8 层就够用了
        changed = False
        for a, b in links:
            if a in seq and b not in seq:
                if seq[-1] == a:
                    seq.append(b); changed = True
                elif seq[0] == a:
                    seq.insert(0, b); changed = True
            elif b in seq and a not in seq:
                if seq[-1] == b:
                    seq.append(a); changed = True
                elif seq[0] == b:
                    seq.insert(0, a); changed = True
        if not changed:
            break
    return seq


def build_link_items(stations: Dict[str, Dict], transfer_links, color_of, scale: float):
    """造出「虚拟换乘虚线」+「同名副站体」两类图元（**不**加进场景，由调用方加）。

    ★ 抽成模块级函数的理由和 `build_line_points` 一样：程序（MapView.rebuild_links）
      和对照图工具（tools/_render_check.py）必须走**同一段代码**，
      否则"改了构建逻辑但对照图没跟着变"⇒ 验了个寂寞。

    返回 (dashes, alts)：前者是 DashedLinkItem 列表，后者是 (key, StationDotItem)。
    """
    dashes: List[DashedLinkItem] = []
    alts: List[tuple] = []

    by_name: Dict[str, tuple] = {}
    for sid, d in stations.items():
        nm = d.get("station_name")
        if nm and nm not in by_name:
            by_name[nm] = (sid, d)

    def pos_of(name):
        e = by_name.get(name)
        if not e:
            return None
        return QPointF(float(e[1].get("x", 0)), float(e[1].get("y", 0)))

    def add_dash(p0: QPointF, p1: QPointF, dist: str, owners=()) -> None:
        it = DashedLinkItem(p0, p1, dist or "", owners=owners)
        it.apply_view_scale(scale)
        dashes.append(it)

    # ① 不同名两站之间（新澜↔观澜 等）
    for d in (transfer_links or []):
        ea, eb = by_name.get(d.get("a")), by_name.get(d.get("b"))
        if not ea or not eb:
            continue
        add_dash(pos_of(d.get("a")), pos_of(d.get("b")), d.get("distance") or "",
                 owners=(ea[0], eb[0]))

    # ② 同名双站体（湖贝 2/5、红岭南 9/11、清湖 4/有轨电车、坪山中心 14/云巴）
    for sid, data in stations.items():
        bodies = data.get("alt_bodies") or []
        if not bodies:
            continue
        # ★ v2.6.65：pill.merge=1 的站（福田口岸）——胶囊本体横跨主/副站体
        #   把它们连成一体，副站体圆点+灰虚线都不要再画（第二份"站名"也随之
        #   消失，全站只剩主图元那一个文字）。
        if (data.get("pill") or {}).get("merge"):
            continue
        nm = data.get("station_name") or sid
        p0 = QPointF(float(data.get("x", 0)), float(data.get("y", 0)))
        for i, b in enumerate(bodies):
            try:
                p1 = QPointF(float(b["x"]), float(b["y"]))
            except (KeyError, TypeError, ValueError):
                continue
            alt_lid = str(b.get("line") or "")
            alt_id = "%s@alt%d" % (sid, i)
            alt_data = {
                "station_id": alt_id,
                "station_name": nm,
                "lines": [alt_lid] if alt_lid else [],
                "x": p1.x(), "y": p1.y(),
                "is_transfer": False,
                # ★ v2.6.82：副站体站名的手动偏移/方位（用户拖出来的）。
                #   存在 alt_bodies[i] 里（见 main_window._on_label_moved），
                #   重建时还原 —— 否则拖完一重建就弹回自动摆位。
                "label_dx": float(b.get("label_dx") or 0.0),
                "label_dy": float(b.get("label_dy") or 0.0),
                "label_side": b.get("label_side") or "",
            }
            dot = StationDotItem(alt_id, alt_data, color=color_of(alt_lid))
            dot.apply_view_scale(scale)
            # ★ v2.6.88：副站体**可拖**了（云巴/有轨电车的换站点本来就属于这类）
            #   —— v2.6.82 曾因"拖得动却存不下来"改成纯展示；现在拖动收尾走
            #   map_view 的确定性落盘（alt_bodies[i].x/y + 撤销），不再有假象。
            dot.setAcceptedMouseButtons(Qt.LeftButton)
            dot.setAcceptHoverEvents(False)
            alts.append((alt_id, dot))
            add_dash(p0, p1, b.get("distance") or "", owners=(sid,))

    return dashes, alts


def declutter_link_labels(links, shown, line_idx, line_pad: float,
                          pad: float) -> None:
    """给"约XX米"挑一个不跟别人打架的方向（v2.6.22，**程序与对照图工具共用**）。

    背景（用户原话）：「你现在和原图好多都没有对照上。按照观看最佳的方式去修改」。
    米数原来**死死钉在两端中点** ⇒ 坪山那一片三条米数
    （坪山高铁站↔坪山 100m、未来城↔坪山广场 450m、坪山中心↔坪山中心 450m）
    叠成一坨，还压住"站前路东 / 坪山广场"这些站名。

    优先级：① 不压别的米数、不压站名、不压站点圆点；② 不压线路；
    ③ 越靠前的候选方向越优先（中点 → 四正 → 四斜 → 外一圈）。
    全都压着时选**压得最少**的那个 —— 绝不因此不显示：米数是用户点名要的信息。

    参数：
      links    : DashedLinkItem 列表（只有带 label 的会动）
      shown    : 参与避让的 StationDotItem 列表（主站 + 副站体）
      line_idx : LineSegIndex 或 None（None 就跳过"压线"打分）
      line_pad : 压线判定的半宽（场景单位）
      pad      : 米数与障碍物之间的额外留白（场景单位）
    """
    links = [it for it in (links or []) if getattr(it, "label", None) is not None]
    if not links:
        return
    if not LINK_LABEL_AVOID:
        for it in links:
            it.set_label_side("mid")
        return

    # 已占位：所有**已显示**的站名（含副站体）
    taken: List[QRectF] = []
    for it in (shown or []):
        try:
            if not it.is_label_visible():
                continue
            taken.append(it.label.sceneBoundingRect().adjusted(-pad, -pad, pad, pad))
        except (AttributeError, RuntimeError):
            continue
    # 站点圆点（含副站体）也是障碍物
    dots: List[QRectF] = []
    for it in (shown or []):
        try:
            rr = it.radius()
            p = it.pos()
        except (AttributeError, RuntimeError):
            continue
        dots.append(QRectF(p.x() - rr, p.y() - rr, rr * 2, rr * 2))

    def overlap(rs: QRectF, rects) -> float:
        area = 0.0
        for other in rects:
            inter = rs.intersected(other)
            if not inter.isEmpty():
                area += inter.width() * inter.height()
        return area

    # ★ v2.6.30：`taken` 只放**站名/圆点**，米数自己占的位子单独放 `taken_lk`。
    #   以前两者混在一个列表里按"重叠面积"排序 ⇒ 会出现"为了少压 2px 站名，
    #   去压另一条米数 200px"的怪事（0.25 档实测米数之间多出 2 对重叠）。
    #   现在优先级明确：① 不压别的米数 ② 不压站名/圆点 ③ 不压线路。
    taken_lk: List[QRectF] = []

    # 顺序固定（按两端端点排）：多次重建结果稳定，不做无谓的位置跳变
    links.sort(key=lambda it: (it.p0.x(), it.p0.y(), it.p1.x(), it.p1.y()))
    for it in links:
        best = None
        cur = it.label_side
        order = [cur] + [s for s in LINK_LABEL_SIDES if s != cur]

        def _scan(cands, i0: int):
            """在这批候选里挑最好的；返回 (best, 命中完全干净)。"""
            b = None
            for _j, side in enumerate(cands):
                r = it.label_rect_for_side(side)
                if r.width() <= 0.1 or r.height() <= 0.1:
                    continue
                a_lk = overlap(r, taken_lk)
                a_st = overlap(r, taken) + overlap(r, dots)
                hits = 0.0 if line_idx is None else line_idx.hit_length(r, line_pad)
                key = (1 if a_lk > 0.0 else 0, a_lk,
                       1 if a_st > 0.0 else 0, a_st, hits, i0 + _j)
                if b is None or key < b[0]:
                    b = (key, side, r)
                if a_lk == 0.0 and a_st == 0.0 and hits == 0.0:
                    return b, True      # 完全干净 → 不再找
            return b, False

        best, _clean = _scan(order, 0)
        if not _clean:
            # ★ v2.6.30：站名改成照抄原图方位后，有的米数原来的落点被站名占了，
            #   "换方向"最多只能让开 3 个框 ⇒ 再补一条"沿虚线滑动"的路。
            #   ★★ 只在**原候选躲不开时**才滑：滑动会挪到别人（别条米数）碗里，
            #      实测一股脑加进候选会让 0.25 档米数之间多出 2 对重叠。
            best2, _c2 = _scan(["%s@%d" % (s, t) for t in (18, 32, 68, 82)
                                for s in LINK_LABEL_SIDES], 1000)
            if best2 is not None and (best is None or best2[0] < best[0]):
                best = best2
        if best is None:
            continue
        _key, side, r = best
        it.set_label_side(side)
        taken_lk.append(r.adjusted(-pad, -pad, pad, pad))


def line_station_xy(st: Dict, line_id: str):
    """某条线经过这个站时，该用**哪个坐标**。

    ★★ v2.6.21 修的坑：同名站被拆成两个站体时（湖贝 2号线 / 湖贝 5号线），
      站记录的主坐标是其中一个站体，另一个在 `alt_bodies` 里。
      渲染线路时若一律用主坐标，**走另一条线的那条线就会被拽过去**：
      实测湖贝的 5号线（紫）在站上被从 y=5034 硬拉到 y=5124，
      画出一个明显的 **V 形折角**，而原图是直着穿过去的。
    ⇒ 判断"这个站有没有属于本线自己的站体"，有就用它的坐标。

    ★ 只在 `alt_bodies[].line == 本线` 时替换，其余情况原样返回主坐标。
    """
    for b in (st.get("alt_bodies") or []):
        if str(b.get("line") or "") == str(line_id):
            try:
                return float(b["x"]), float(b["y"])
            except (KeyError, TypeError, ValueError):
                break
    return float(st.get("x", 0)), float(st.get("y", 0))


def load_elbow_sides() -> Dict[str, str]:
    """读 `data/elbow_sides.json`：每段 45° 斜线贴哪一头（照原图逐段量出来的）。

    ★★ v2.6.24：用户原话「你很多的弯曲方向和原图都是相反的」。
      我们原来把 45° 斜线**一律贴在起点那一端**，实测原图 121 段里有 66 段
      是贴在终点那一端（`tools/measure_elbow_side.py` 用该线颜色的距离场判定，
      结论明确的 119 段**没有一段分不出来**）。
      键 = "<线号>|<上一站>|<下一站>"，值 "a"/"b"。
    ★ 读不到就当空表（= 全部退回旧画法），绝不因为数据文件缺失而崩。
    """
    if os.environ.get("METROEDITOR_NO_ELBOW_FIX", "0") == "1":
        return {}                     # A/B 开关：精确复现"斜线一律贴 a 端"的旧行为
    # ★ v2.6.57：**先读用户数据目录**，再回退打包内的那份。
    #   `rename_station()` 改完站名后写的是 DATA_DIR；如果这里还是只读
    #   `__file__` 那一份（打包后指向临时解包目录 _MEIPASS），改完的名字
    #   下次启动就失效了。两边必须成对。
    for p in _station_keyed_json_candidates("elbow_sides.json"):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(d, dict):
            return {str(k): str(v) for k, v in d.items()}
    return {}


def _station_keyed_json_candidates(filename: str) -> List[Path]:
    """"以站名为键"的独立 json 的查找顺序。

    ★★ 只有一份实现（`core.data_manager.station_keyed_json_candidates`）——
       读（这里）和写（`rename_station`）必须同序，否则"写进去了却读不到"。
    """
    from core.data_manager import station_keyed_json_candidates
    return station_keyed_json_candidates(filename)


_ELBOW_SIDES: Optional[Dict[str, str]] = None


def elbow_sides() -> Dict[str, str]:
    """`load_elbow_sides()` 的进程内缓存（文件只在启动后第一次用时读一次）。"""
    global _ELBOW_SIDES
    if _ELBOW_SIDES is None:
        _ELBOW_SIDES = load_elbow_sides()
    return _ELBOW_SIDES


# ★ v2.6.53：用户对"某条线的某一段"指定的形状（Ctrl 点两站 → 右键菜单设的）。
#   键 "<线号>|<上一站>|<下一站>"（与 elbow_sides 同格式），值：
#     "cup" = 凸弧（弧顶朝上/朝外）、"cap" = 凹弧
#   ★★ 存在 `lines_doc["segment_shapes"]`（**不是**独立 json）——
#      `dm.save()` 会把整个 lines_doc 落盘、`_snapshot()` 深拷贝 lines_doc
#      ⇒ 落盘 + Ctrl+Z 撤销**自动就有**；像 elbow_sides.json 那样放独立文件的话
#      既不落盘也不可撤销（改完重启就没了）。
ARC_BULGE = float(os.environ.get("METROEDITOR_ARC_BULGE", "0.18"))


def segment_shapes() -> Dict[str, str]:
    """每次都从 lines_doc 现读（不缓存）：数据随时会被菜单改写，缓存会拿到旧值。"""
    try:
        d = get_data_manager().lines_doc.get("segment_shapes") or {}
        return ({str(k): str(v) for k, v in d.items()}
                if isinstance(d, dict) else {})
    except Exception as e:
        print("[segment_shapes] 读取失败：", repr(e))
        return {}


def traced_paths() -> Dict[str, list]:
    """★ v2.6.55 自动描线（甲）：用户对"某条线的某一段"照**官方原图**描出来的路径。

    键 "<线号>|<上一站>|<下一站>"（与 elbow_sides / segment_shapes 同格式），
    值 = [[x, y], ...] 一串**场景坐标**（== 官方原图像素，见 UNDERLAY_SCENE）。

    ★★ 同样存在 `lines_doc["traced"]` ⇒ 落盘 + Ctrl+Z 撤销自动就有。
    ★ 路径是**绝对坐标**，画的时候原样铺点 —— 站点被挪走后这段就"过期"了，
      渲染时由 `_traced_fresh()` 判定（两端离站点太远就当没描过，退回原画法）。
    """
    try:
        d = get_data_manager().lines_doc.get("traced") or {}
        return ({str(k): v for k, v in d.items() if isinstance(v, (list, tuple))}
                if isinstance(d, dict) else {})
    except Exception as e:
        print("[traced_paths] 读取失败：", repr(e))
        return {}


def octi_off_paths() -> set:
    """★ v2.6.63：**不许八向化**的那些段（键格式同 traced）。

    用户原话：「很多地方都有奇怪的扭曲，根本无法修复，你来自动探测并修复」。
    病根：官方原图里有些段是**平滑的弧**（例：13号线 光明城→德雅路 向右鼓 120px），
    而 v2.6.61 起描线边也走八向化 ⇒ 弧被拆成"45°斜线 + 36px 短竖线"，
    再叠上圆角倒角 ⇒ 屏幕上就是个扭曲的月牙。

    名单由 `tools/fix_octi_twist.py` 离线算出来（判据：同一段"八向化后"与"原样"
    两条路径，谁离**官方同色像素**更近）。存在 `lines_doc["octi_off"]`
    ⇒ 落盘 + Ctrl+Z 撤销自动就有。
    """
    try:
        d = get_data_manager().lines_doc.get("octi_off") or []
        if isinstance(d, str):
            d = [d]
        return {str(k) for k in d if k}
    except Exception as e:
        print("[octi_off_paths] 读取失败：", repr(e))
        return set()


def _traced_fresh(path, ax: float, ay: float, bx: float, by: float,
                  tol: float = 90.0) -> bool:
    """这段描线路径还"接得上"当前两站吗（站点被拖走后就过期了）。"""
    if not path or len(path) < 2:
        return False
    try:
        p0, p1 = path[0], path[-1]
    except Exception:
        return False
    d0 = ((float(p0[0]) - ax) ** 2 + (float(p0[1]) - ay) ** 2) ** 0.5
    d1 = ((float(p1[0]) - bx) ** 2 + (float(p1[1]) - by) ** 2) ** 0.5
    span = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
    return d0 <= max(tol, span * 0.6) and d1 <= max(tol, span * 0.6)


def arc_samples(a: "QPointF", b: "QPointF", kind: str, n: int = 12):
    """二次贝塞尔的**中间**采样点（不含首尾两端）。

    ★ 法线统一朝"上"（y 分量为负）⇒ **凸弧 = 往上/往外鼓**，符合直觉
      （地铁图里说"凸"通常指这段线向上拱起）。凹弧就是反方向。
    """
    dx, dy = b.x() - a.x(), b.y() - a.y()
    L = (dx * dx + dy * dy) ** 0.5
    if L < 1e-6:
        return []
    nx, ny = -dy / L, dx / L
    if ny > 0:                      # 翻成"朝上"，保证 cup/cap 在任意走向下含义一致
        nx, ny = -nx, -ny
    sign = 1.0 if kind == "cup" else -1.0
    cx = (a.x() + b.x()) * 0.5 + nx * sign * L * ARC_BULGE
    cy = (a.y() + b.y()) * 0.5 + ny * sign * L * ARC_BULGE
    out = []
    for k in range(1, n):
        t = k / float(n)
        u = 1.0 - t
        out.append(QPointF(u * u * a.x() + 2 * u * t * cx + t * t * b.x(),
                           u * u * a.y() + 2 * u * t * cy + t * t * b.y()))
    return out


_TERMINAL_BADGES: Optional[Dict[str, Dict]] = None


def load_terminal_badges() -> Dict[str, Dict]:
    """读 `data/terminal_badges.json`：每个线路末端的号码方块**照原图量出来**的摆位。

    ★★ 为什么要量：先试过"沿末段往外推"，莲塘/溪涌/红岭南/东角头/田心 这 5 个
      原图是**竖着**摆的，推出来全是横的，误差 250px 上下 —— 原图摆位是
      "看哪儿有空地往哪儿放"，推不出来。
      键 = "<线号>|<站名>"，值 = {"ux","uy","dist","size"}
      （ux/uy 是单位方向，dist 是方块中心离站体的距离；实测 101~209、中位数 183）。
    ★ 读不到就当空表（全部走兜底规则），绝不因为数据文件缺失而崩。
    """
    if os.environ.get("METROEDITOR_NO_TERMINAL_BADGE", "0") == "1":
        return {}                      # A/B 开关：退回"沿末段往外"的老画法
    global _TERMINAL_BADGES
    if _TERMINAL_BADGES is None:
        # ★ v2.6.57：同 `load_elbow_sides` —— 先读用户数据目录（改名后写的是那里）
        got = {}
        for p in _station_keyed_json_candidates("terminal_badges.json"):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(d, dict):
                got = d
                break
        _TERMINAL_BADGES = got
    return _TERMINAL_BADGES


def badge_offsets_file() -> Path:
    """用户手动拖出来的线路号偏移（`data/badge_offsets.json`）。

    ★ 为什么**不写回** `terminal_badges.json`：那份文件是"照原图逐个量出来的
      真值"（`tools/measure_terminal_badges.py` 的产物），一旦被用户拖动改写，
      就再也分不清"原图本来在哪"和"用户挪到哪"了。
      所以用户改动单独存一份**叠加**上去，量出来的基线永远干净、可回滚。
    ★ 目录用 data_manager 的 DATA_DIR：打包后是 exe 同级的 `data/`
      （`__file__` 那种取法在 onefile 里指向临时解包目录，写进去重启就没了）。
    """
    from core.data_manager import DATA_DIR
    return Path(DATA_DIR) / "badge_offsets.json"


def load_badge_offsets() -> Dict[str, list]:
    """读用户拖动记录：`{"4|福田口岸": [dx, dy], ...}`（场景单位）。"""
    try:
        with open(badge_offsets_file(), "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_badge_offsets(d: Dict[str, list]) -> None:
    """原子写：先落临时文件再 replace，避免写到一半崩溃留下半个 JSON。"""
    p = badge_offsets_file()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except OSError:
        pass


def build_terminal_badge_specs(stations, lines):
    """算出"每条线两端该摆哪个线路号方块、摆在哪"——**纯数据，不碰 Qt**。

    返回 `[(key, lid, x, y, ux, uy, dist, lane), ...]`，含义见
    `TerminalBadgeItem.set_layout`。
    ★ 程序（`rebuild_terminal_badges`）与对照图工具（`tools/_render_check.py`）
      共用这一份：两处各写一份，画出来的图必然不一样。

    摆位三条来源，按优先级：
      ① 量到了（`terminal_badges.json`）⇒ 直接用 (ux, uy, dist)，lane=0；
      ② 同一站另一条线量到了 ⇒ 把它**沿垂直轴镜像**过来。
         福田口岸 "10" 量到 (+29,+188)，4号线镜像成 (-29,+188)，
         落点 (3491,6137) vs 原图 (3490,6134) —— 差 3px；
      ③ 都没量到 ⇒ 兜底：沿末段往外、八方向取整、距离 175，同站多个号并排。
    用**线路自己的站序**（不是贯通后的）——2号线和8号线是两条线，
    各自的号码要摆在自己的终点上。
    """
    data = load_terminal_badges()
    wants: Dict[str, List[tuple]] = {}
    for line in lines:
        lid = str(line.get("id"))
        # ★ 有轨电车/云巴这类"名字不是线路号"的线不摆方块（原图也没有）
        if any('\u4e00' <= c <= '\u9fff' for c in lid):
            continue
        seq = [s for s in (line.get("stations") or []) if s in stations]
        if len(seq) < 2:
            continue
        for end_i, nb_i in ((0, 1), (-1, -2)):
            nm, nb = seq[end_i], seq[nb_i]
            st, sbn = stations[nm], stations[nb]
            x, y = line_station_xy(st, lid)
            nx, ny = line_station_xy(sbn, lid)
            dx, dy = x - nx, y - ny
            if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                dx, dy = 0.0, 1.0
            # ★ 键**只按站名**：同一站的方块必须一起处理。带 end_i 就废了 ——
            #   福田口岸在 4号线是 index 0、在 10号线是 index -1，
            #   键一不同就分成两组，两个方块各摆各的（原图是并排的）。
            wants.setdefault(nm, []).append((lid, x, y, dx, dy, nm))

    out = []
    for key, lst in wants.items():
        g = sorted(lst, key=lambda e: e[0])          # 线号排序，结果稳定
        meas = {}
        for e in g:
            d = data.get("%s|%s" % (e[0], key))
            if isinstance(d, dict):
                meas[e[0]] = d
        if meas:
            ref = meas[sorted(meas)[0]]
            rux = float(ref.get("ux", 0.0) or 0.0)
            ruy = float(ref.get("uy", 0.0) or 0.0)
            rdist = float(ref.get("dist", 0.0) or 0.0) or (BADGE_SCENE * 0.5 + BADGE_GAP)
            # 主轴 = 分量大的那个轴；没量到的线把**垂直分量**翻过去
            flip_x = abs(ruy) >= abs(rux)
            for lid, x, y, _dx, _dy, _nm in g:
                if lid in meas:
                    m = meas[lid]
                    ux = float(m.get("ux", rux) or 0.0)
                    uy = float(m.get("uy", ruy) or 0.0)
                    dist = float(m.get("dist", rdist) or 0.0) or rdist
                else:
                    ux, uy = (-rux if flip_x else rux), (ruy if flip_x else -ruy)
                    dist = rdist
                out.append((key, lid, x, y, ux, uy, dist, 0.0))
            continue

        # ③ 兜底：沿末段往外（八方向取整），同站多个号沿垂直方向并排
        sdx = sum(e[3] for e in lst)
        sdy = sum(e[4] for e in lst)
        if abs(sdx) < 1e-6 and abs(sdy) < 1e-6:      # 互相抵消 ⇒ 退回第一条
            sdx, sdy = lst[0][3], lst[0][4]
        ang = round(math.atan2(sdy, sdx) / (math.pi / 4)) * (math.pi / 4)
        ux, uy = math.cos(ang), math.sin(ang)
        ux = 0.0 if abs(ux) < 1e-9 else ux
        uy = 0.0 if abs(uy) < 1e-9 else uy
        # ★ 并排要以"这组站体的平均位置"为锚，不然整组会被拉偏
        ax = sum(e[1] for e in g) / len(g)
        ay = sum(e[2] for e in g) / len(g)
        for i, (lid, x, y, _dx, _dy, _nm) in enumerate(g):
            out.append((key, lid, ax, ay, ux, uy,
                        BADGE_SCENE * 0.5 + BADGE_GAP, i - (len(g) - 1) / 2.0))
    return out


def build_line_points(line_id: str, seq, stations) -> List[QPointF]:
    """把一条线的站序变成**渲染用的点列**（含换乘站的走廊偏移）。
    —— 只要点，不要折点方向；需要折点方向请用 `build_line_points_ex()`。
    """
    return build_line_points_ex(line_id, seq, stations)[0]


# ★★ v2.6.56：走廊替身点**单侧最多吃段长的这个比例**（两端合计 ≤70%）。
#   病因（用户原话「在两站都是换乘站的情况下，线路的轨道会出现严重变形」）：
#   相邻两站都插替身点时，各自 min(120, 0.45×沿走廊投影) 是**各算各的**，
#   两端加起来能盖住 90% 段长，只剩十几像素自由段；而两条走廊的横向错位
#   （几十像素的测量误差级）全挤在那十几像素里 ⇒ 线变成一个陡峭的小台阶。
#   实测 12 号线 国展→国展北：段长 197，两端各伸 92（合计 184），
#   自由段只剩 12.5px，横向错位 12px ⇒ 一个 45° 急折。
#   修法 = 替身点长度再受"站距 × 本比例"约束 ⇒ 错位被摊到足够长的斜线上
#   （45° 急折 → 11° 平滑过渡），站区沿走廊直穿的作用也仍然保留。
#   设 1.0 退回 v2.6.55 的旧行为（回归 _chk_transfer_pair 用它做变异自检）。
STUB_MAX_FRAC = float(os.environ.get("METROEDITOR_STUB_FRAC", "0.35"))


def build_line_points_ex(line_id: str, seq, stations, want_keys: bool = False):
    """把一条线的站序变成**渲染用的点列**（含换乘站的走廊偏移）+ 折点方向表。

    返回 `(pts, elbows)`：`elbows[i]` 描述 `pts[i-1] → pts[i]` 这一段的 45°
    斜线贴哪一头（见 `elbow_sides()`）；`elbows` 比 `pts` 多一个（下标 0 是占位）。
    只要点列表请用 `build_line_points()`。

    ★ `want_keys=True` 时多返回一份 `keys`：`keys[i]` 是 `pts[i-1] → pts[i]`
      这一段**属于哪两个站**（"<线号>|<上一站>|<下一站>"，替身点的段是 ""）。
      tools/measure_elbow_side.py 靠它**按真正画出来的点段**去量原图 ——
      少了它，量的是"站到站的直线"，而实际画的是走廊偏移后的点，
      88% 的折点方向会贴到根本不需要折的段上（实测 66 条 b 只生效 8 条）。

    ★★ v2.6.20：换乘站里每条线**各占一条走廊**，不都挤到站中心。
      用户原话「原图是为了错开，而你还是把他们聚集到了一起」。
      每个站的 lanes[线号] = [dx, dy, 走廊走向角, 拟合拉长度]，全部由
      tools/measure_transfer_layout.py 从原图逐个量出
      （原图像素 == 场景单位）。例：车公庙 7/9/11 号线的 x 偏移分别是
      −49 / +6 / +51、走廊走向都是 90°（竖），1 号线偏移 0、走向 0°（横）
      —— 和原图三条竖走廊完全对齐。

    ★ 为什么还要「走廊穿越段」：只把点挪到走廊上，线在站上仍是一个尖角
      （上一站 → 偏移点 → 下一站），相邻两条斜线会在药丸下方**交叉打结**
      （实测车公庙 7 号线与 11 号线就是）。原图里这些线是"顺着走廊竖着
      穿过去"的。所以在站前后各插一个沿走廊方向的替身点，让线在站区先走
      一段直线 —— 交叉随之消失。

    ★★ 抽成模块级函数是为了让 tools/_render_check.py 与程序**共用同一段
      代码**：验证工具自己再写一遍，就会"改坏了也验不出来"。

    ★ 调试开关 `METROEDITOR_NO_LANES=1` ⇒ 完全忽略走廊偏移（退回 v2.6.19 的
      "所有线都过站中心"）。用来做 A/B 对照，判断某个回归失败到底是
      这个改动引入的、还是本来就有的。
    """
    use_lanes = os.environ.get("METROEDITOR_NO_LANES", "0") != "1"
    _eb = elbow_sides()
    _seg = segment_shapes()          # ★ v2.6.53：用户设的"凸弧/凹弧"
    _tr = traced_paths()             # ★ v2.6.55：自动描线（照官方原图）
    _oo = octi_off_paths()           # ★ v2.6.63：官方是平滑弧的段 ⇒ 不许八向化
    raw = []
    offs = []                        # ★ v2.6.56：每站的"走廊落脚点"（算站距用）
    for name in seq:
        st = stations.get(name)
        if not st:
            continue
        sx, sy = line_station_xy(st, line_id)
        raw.append((sx, sy, st))
        _o = (st.get("lanes") or {}).get(str(line_id)) if use_lanes else None
        _ox, _oy = float(sx), float(sy)
        if _o:
            try:
                _ox, _oy = float(sx) + float(_o[0]), float(sy) + float(_o[1])
            except (IndexError, TypeError, ValueError):
                _ox, _oy = float(sx), float(sy)
        offs.append((_ox, _oy))
    pts: List[QPointF] = []
    ebl: List[str] = [""]                     # ebl[i] 描述 pts[i-1] → pts[i]
    keys: List[str] = [""]                    # keys[i] = 这一段属于哪两个站
    _sp_idx = -1                              # ★ v2.6.59：pts 里"上一站自己那个点"的下标
    for i, (x, y, st) in enumerate(raw):
        ox, oy = x, y
        through = None
        # ★ 这一段（上一站 → 本站）的折点方向，照原图查表；查不到 = 旧的 "a"
        pair = ""
        key = ""
        if i > 0:
            key = "%s|%s|%s" % (line_id, seq[i - 1], seq[i])
            pair = _eb.get(key, "a")
        # ★ v2.6.63：这一段在"免八向化"名单里（官方画的是**平滑的弧**，离线判过）。
        #   ★★ 不能加 `and key not in _tr`：描线路径**过期**时（站点被拖走过）
        #   下面的 trace 分支会整个跳过、fall through 到这里 —— 那时候描线等于
        #   没有，名单照样该生效（实测「原样更贴 12 段」里有好几段就是这种：
        #   描线点与两站坐标完全重合 ⇒ trace 分支实际只在 ebl 的"下一格"写了
        #   traceNS，本段那条边仍是空的 ⇒ 名单形同虚设，八向化照样插拐点）。
        _oo_plain = bool(i > 0 and key in _oo)
        off = st.get("lanes") if use_lanes else None
        d = off.get(str(line_id)) if off else None
        if d:
            ox, oy = x + float(d[0]), y + float(d[1])
            try:
                if float(d[3]) >= 3.0:            # 走廊拟合得够直才敢用
                    through = round(float(d[2]) / 45.0) * 45.0
            except (IndexError, TypeError, ValueError):
                through = None
        # ★ v2.6.53：这一段被设成了**弧** ⇒ 铺一串贝塞尔采样点画出来。
        #   ① 采样点标 "arc"，`octilinear_waypoints_tagged` 见到就**不八向化**；
        #   ② **跳过走廊替身点** —— 替身点是沿走廊的直线，会把弧从中间掰断。
        if i > 0 and pts and _seg.get(key) in ("cup", "cap"):
            bpt = QPointF(ox, oy)
            for qp in arc_samples(pts[-1], bpt, _seg.get(key)):
                pts.append(qp)
                ebl.append("arc")
                keys.append(key)
            pts.append(bpt)
            ebl.append("arc")
            keys.append(key)
            _sp_idx = len(pts) - 1
            continue
        # ★ v2.6.55 自动描线（甲）：这一段照**官方原图**描过 ⇒ 直接把那串点铺上去，
        #   不走八向化。"trace" = 中间点（允许倒圆角），"traceS" = 末端的站点
        #   （必须精确过点）。★ 站点被拖走后路径会过期 ⇒ _traced_fresh() 兜底退回。
        if i > 0 and pts and key in _tr:
            _tp = _tr[key]
            # ★★ v2.6.59：上一站的**出站替身点**是为"顺走廊直穿"插的（沿走廊往外
            #   伸 90~120px），而描线路径自带官方走法 ⇒ 留着它，线会先冲出去再折
            #   回来。实测 7号线 黄木岗→八卦岭：冲出 90.5px 再折回站点，多出一条
            #   100.6px 的回头边、顶点转角 113°（`_chk_transfer_pair` 的"短边急折"
            #   就是它）。⇒ 铺描线之前先把上一站点之后的替身点**撤掉**。
            if _sp_idx >= 0 and len(pts) > _sp_idx + 1:
                del pts[_sp_idx + 1:]
                del ebl[_sp_idx + 2:]
                del keys[_sp_idx + 2:]
            _a = pts[-1]
            if _traced_fresh(_tp, _a.x(), _a.y(), ox, oy):
                # ★ v2.6.63：这一段官方画的是**平滑的弧**（离线判过：原样比八向化
                #   更贴官方像素）⇒ 标签换成 traceN/traceNS，渲染器见到就原样连。
                _e1 = "traceN" if key in _oo else "trace"
                _e2 = "traceNS" if key in _oo else "traceS"
                # ★★ **从上一站出来的那条边**也要免八向化 —— 只改描线点的话，
                #    弧的第一截还是会被掰成"45°斜线 + 直线"（实测：11 段里只修好
                #    6 段，剩下的就是漏了这条边）。
                # ★ v2.6.59：描线路径的首/末点**就是两个站的坐标**，而这里
                #   `pts[-1]` 已经是上一站、末尾还会再 append 本站点 ⇒
                #   原样铺会各多出一个 **0px 的"零长度边"**，渲染出来就是
                #   180° 急折（`_chk_transfer_pair` 的"折点扎堆"被它打回原形，
                #   实测 1号线 世界之窗→华侨城 两个折点只隔 0.5px）。
                #   ⇒ 首尾若与站点重合就跳过，绝不重复铺点。
                _seq = list(_tp)
                try:
                    if _seq and math.hypot(float(_seq[0][0]) - _a.x(),
                                           float(_seq[0][1]) - _a.y()) < 1.0:
                        _seq = _seq[1:]
                    if _seq and math.hypot(float(_seq[-1][0]) - ox,
                                           float(_seq[-1][1]) - oy) < 1.0:
                        _seq = _seq[:-1]
                except (TypeError, ValueError, IndexError):
                    _seq = list(_tp)
                # ★★ **从上一站出来的那条边**也要免八向化 —— 只改中间点的话，
                #    弧的第一截还是会被掰成"45°斜线 + 直线"（实测：11 段里只修好
                #    6 段，剩下的就是漏了这条边）。
                #    ★★★ 但**必须在 `_seq` 非空时才改**：`ebl[len(pts)]` 是"预留给
                #    即将 append 的那个点"的一格。若 `_seq` 为空（描线点与站点重合、
                #    整段被跳过），这一格是留给**本站**的 ⇒ 写成 traceN 会让本站
                #    变成"可倒圆角的中间点"，渲染出的线离站中心 13~27px
                #    （`_chk_station_on_line` A 挂在 6/上屋 27.08、5/下水径 13.14）。
                #   ★★★ v2.6.63 修正：`_seq` **为空**时（描线点全与两站重合，整段
                #   只剩"上一站 → 本站"一条边）也要改那一格 —— 而且终点是**本站**
                #   ⇒ 必须用 `_e2`(traceNS)，用 `_e1`(traceN) 会把本站当中间点、
                #   弧顶不过站。实测不改的话 12 段名单全是死条目，复核永远归不了零。
                if key in _oo and 0 <= len(pts) < len(ebl):
                    ebl[len(pts)] = _e1 if _seq else _e2
                for q in _seq:
                    try:
                        pts.append(QPointF(float(q[0]), float(q[1])))
                    except (TypeError, ValueError, IndexError):
                        continue
                    ebl.append(_e1)
                    keys.append(key)
                # ★★ v2.6.59：`elbows[i]` 描述的是 **pts[i] 出去的那条边**，
                #   所以"最后一个描线点的标签"决定的是**本站**是不是站点。
                #   标 "trace" ⇒ 本站被当成"可倒圆角的中间点"，弧顶不再过站
                #   （补偿量 r·sin(θ/2)/2 没了）⇒ 实测 1号线 大新 转角 24.5°、
                #   r=62.5 ⇒ 弧顶离站 6.63px（`_chk_station_on_line` A 直接挂掉）。
                #   ⇒ 通向本站的那条边必须标 "traceS"。
                if _seq:
                    ebl[-1] = _e2
                pts.append(QPointF(ox, oy))
                ebl.append(_e2)
                keys.append(key)
                _sp_idx = len(pts) - 1
                continue
        if through is not None and 0 < i < len(raw) - 1:
            ua = math.radians(through)
            ux, uy = math.cos(ua), math.sin(ua)
            # ★★ 走廊段必须插在"正确的那一侧"：之前写死成 p∓u*seg，害得
            #    11 号线在车公庙先冲过头再折回来（渲染出一个三角形）。
            #    正确做法：看前后邻站分别落在走廊轴的哪一侧（投影符号），
            #    进站侧的点就往邻站那一侧伸、出站侧的点往另一侧伸。
            px, py = raw[i - 1][0], raw[i - 1][1]
            nx, ny = raw[i + 1][0], raw[i + 1][1]
            tp = (px - x) * ux + (py - y) * uy      # 上一站投影
            tn = (nx - x) * ux + (ny - y) * uy      # 下一站投影
            sp = 1.0 if tp > 0 else -1.0
            sn = 1.0 if tn > 0 else -1.0
            if sp != sn:                            # 前后站在两侧 → 才是"穿过"
                # ★★ v2.6.56：长度**必须再受站距约束**（见 STUB_MAX_FRAC 的说明）。
                #   少了它，相邻两站都插替身点时会把整段吃光，只剩十几像素
                #   消化两条走廊的横向错位 ⇒ 一个 45° 急折（"轨道严重变形"）。
                _dv = math.hypot(offs[i][0] - offs[i - 1][0],
                                 offs[i][1] - offs[i - 1][1])
                _dn = math.hypot(offs[i + 1][0] - offs[i][0],
                                 offs[i + 1][1] - offs[i][1])
                bp = (min(120.0, 0.45 * abs(tp), STUB_MAX_FRAC * _dv)
                      if abs(tp) > 1e-6 else 0.0)
                bn = (min(120.0, 0.45 * abs(tn), STUB_MAX_FRAC * _dn)
                      if abs(tn) > 1e-6 else 0.0)
                if bp >= 15.0:
                    pts.append(QPointF(ox + ux * sp * bp, oy + uy * sp * bp))
                    ebl.append("traceN" if _oo_plain else pair)
                    keys.append(key)
                pts.append(QPointF(ox, oy))
                ebl.append("")                      # 替身点 → 本站：已经对齐了
                keys.append("")
                _sp_idx = len(pts) - 1
                if bn >= 15.0:
                    pts.append(QPointF(ox + ux * sn * bn, oy + uy * sn * bn))
                    ebl.append("")
                    keys.append("")
                continue
        # ★★ 免八向化要改的是**上一站自己那条边**：`elbows` 比点列多一个
        #   （`ebl[i]` 描述 `pts[i-1]` 出去的那条边），此时 pts 的最后一点就是
        #   上一站 ⇒ 它的边在 `ebl[len(pts)]`。改到新 append 的那一项是白改
        #   （实测 12|福围|怀德 改完八向化照样插拐点）。
        #   ★ 从上一站直接进本站 ⇒ 本站**是站点** ⇒ 用 traceNS（traceN 会把本站
        #   当中间点、弧顶不过站 —— v2.6.59 踩过：1号线大新偏 6.63px）。
        if _oo_plain and len(ebl) > len(pts):
            ebl[len(pts)] = "traceNS"
        pts.append(QPointF(ox, oy))
        ebl.append(pair)
        keys.append(key)
        _sp_idx = len(pts) - 1
    return (pts, ebl, keys) if want_keys else (pts, ebl)


SCENE_W = 8000.0
SCENE_H = 8000.0
SCENE_PAD = 2500.0   # sceneRect 相对内容 rect 的兜底外扩量（内容极少/视口极小时用）
ZOOM_VIEW_MARGIN = 0.10   # sceneRect 至少要盖住「当前视口」外扩这么多个视口（每侧）。
                          # 见 _refresh_scene_rect：盖住视口 = 锚点永远钉得住的充分条件；
                          # 这个值同时决定"最多能把地图拖出屏幕多远"（0.10 ≈ 276px @1400宽，
                          # 与改动前固定 pad=2500 的 275px 基本一致）
ZOOM_OUT_BELOW_FIT = 0.88 # 最小缩放 = 「整图适配」× 这个系数（允许比整图再小 12%）

# ★ v2.7.13：鼠标拖画布的**限度** —— 视口的四条边最多贴到「所有元素的最外
#   边界 + PAN_ELEMENT_PAD」这么多空白。用户原话「屏幕右侧的边界就是最右侧的
#   这个元素（可适当保留一点空白）」。
#   60 场景单位 ≈ 1.0 倍下的 60px（约 1 个站点圆点直径多一点），够看出"到边了"。
#   想更紧就调小（0 = 元素紧贴屏幕边），想更松就调大。
PAN_ELEMENT_PAD = 24.0
# ★ v2.7.31：看图模式 sceneRect 的额外富余（屏幕像素）。滚动条 range 是整数，
#   理论余量只有几像素时会被截断成 0 ⇒ 差的那一步拖不动（实测 hsb=0/0）。
VIEW_SCENE_SLACK_PX = 32.0

# ★ v2.7.18：看图模式悬浮命中的宽容度（**照片像素**）—— 圆点半径之外再多认
#   这么多 px，不然小档位上圆点只有 2~3px 宽，鼠标根本压不中。
VIEW_HIT_PAD_PX = 4.0

# ★ v2.6.27：再压一道**绝对**下限 —— 用户原话「限制最小缩放度」。
#   为什么需要：整图 8000 场景单位、视口只有 ~874 ⇒ 整图适配才 0.109，再 ×0.88
#   就到 0.096。那个档位上站名框（屏幕恒定 ~50px 宽）比站距（屏幕 ~25px）还宽，
#   排版根本没有腾挪空间，文字只能"骑"到隔壁站头上 ⇒ 就是用户说的
#   「缩小到一定尺寸文字完全偏离正确位置」。
#   0.18 时站距 ≈ 45 屏幕px，跟站名框（~50px）差不多宽，是"还能读"的临界。
#   用户可调：METROEDITOR_MIN_SCALE=0.109 退回"整图适配"（能看全图但字会挤）。
#
# ★★ v2.6.32：0.18 → **0.30**（用户原话「缩小到最小后会发生奇怪的操作，
#   是否可以锁死最小比例」）。0.18 那档实测只有 224/383 个站名还显示（159 个
#   被排版器判为"放不下"而藏掉）、压线 98/224（43.8%）—— 站名一会儿消失
#   一会儿冒出来，就是"奇怪的操作"的来源。
#   0.30 档实测：压线 2/383（0.5%）、站名 383 个全显示，是"排版还成立"的临界。
# ★★ v2.6.38：0.30 → **0.10**。用户原话「鼠标滚轮连续滚动缩小会造成…
#   整张图消失」，而且「和图片一样」意味着"想缩多小就缩多小"。
#   0.30 那道锁现在可以撤了，因为缩放过程已改成**整屏位图拉伸**（见
#   ZOOM_BITMAP）——"缩小到最小后的奇怪操作"（合成帧/sprite 错位）从根上没了；
#   同时站名改成等比（SCENE_FONT_PX），小档字会自动变小 ⇒ 反而不挤。
#   0.10 ≈ 整图适配（874 视口下 fit≈0.109）⇒ 能看全整图。
#   想退回 0.30 那道锁：METROEDITOR_MIN_SCALE=0.30。
# ★ v2.6.47：**撤回** v2.6.44 的"最小缩放 = 1.0" —— 用户原话「我从没让你锁死
#   滑动条」+ 选「全部撤回」⇒ 最小缩放回到 **0.10**（≈ 整图适配，能看全整图），
#   滑块左端回到 0.05，字体倍率最小回到 0.4。
#   （v2.6.38 定的 0.10：0.30 那道锁可以撤了，因为缩放过程已改成整屏位图拉伸；
#    0.10 ≈ 整图适配，能看全整图。）
# ★ v2.6.51：用户要求「滑块最左端就是 1.00×，不允许出现比 1 小的数字」，
#   且"1 倍"落在他指定的那一档（屏幕上显示的 2.3× ⇒ 内部 0.115）。
#   ★★ 这里必须和滑杆下限（`ScalePanel.zmin`）**同一个数**：滚轮走 MIN_VIEW_SCALE，
#     滑杆走 zmin，两者不一致 ⇒ 拖到最左显示 1.00× 但滚轮还能往下缩 ⇒ 冒出 0.87×
#     这种比 1 小的数（v2.6.47 之前就是这个错：左端 0.05 但实际卡在 0.10）。
MIN_VIEW_SCALE = float(os.environ.get("METROEDITOR_MIN_SCALE", "0.115"))

# ★★ v2.7.0：滚轮**固定档位表**（用户：「滚轮缩放地图，可能存在缩放不准确的问题，
#   即每次滚动缩放比例不一致，你设定好数个固定的缩放比例消除计算产生的bug，
#   不要存在随机计算出来的缩放比例」）。
#   · 表里的数字 = **缩放面板上显示的数字**（面板最远档 = 1.00×，基准 = MIN_VIEW_SCALE）；
#   · 内部变换 scale = 显示值 × ZOOM_BASE；
#   · **跳转定位也走同一套**：`zoom_to_station(默认 2.5)` = 面板显示 2.5×。
# ★★ v2.7.6：档位由「等比 ×1.25、共 20 档」改成**等差 +0.5、封顶 6.00×**
#   （用户原话：「缩放改为每次滚动变化 0.5，最大值设置为 6」）。
#   ★★ 两个数字都是**缩放面板上显示的 × 数**（已向用户确认过）：
#      档位 = 1.00 / 1.50 / 2.00 / 2.50 / … / 6.00，共 11 档；
#      最大档 6.00× ⇒ 内部 6.0 × ZOOM_BASE ≈ 0.69（整图 ≈ 1.00×，
#      最大档只看得到全图约 17% —— 这是用户选的，别自己改回去）。
ZOOM_BASE = MIN_VIEW_SCALE                      # 面板"1.00×"对应的内部缩放
ZOOM_STEP_ADD = 0.5                             # 每格 +0.5（面板显示值，等差）
ZOOM_STEP_MAX_SHOWN = 6.0                       # 最大档 = 面板显示 6.00×
ZOOM_STEP_SHOWN = tuple(
    round(1.0 + ZOOM_STEP_ADD * i, 2)
    for i in range(int(round((ZOOM_STEP_MAX_SHOWN - 1.0) / ZOOM_STEP_ADD)) + 1))
ZOOM_STEPS = tuple(s * ZOOM_BASE for s in ZOOM_STEP_SHOWN)
# ★ 内部上限 = 末档。滚轮和滑块**同一个数**（跟 MIN_VIEW_SCALE 那边的教训一样：
#   两边不一致 ⇒ 拖到底显示一个数、滚轮却停在另一个数）。
ZOOM_MAX_SCALE = ZOOM_STEPS[-1]
# 滚轮"一格"的 delta（Qt 标准鼠标滚轮一格 = 120；触控板的小 delta 攒够一格才走）
WHEEL_STEP_UNIT = 120.0
# ★★ v2.6.38：缩放手势期间，画面 = **手势开始时抓的一张整屏位图在拉伸**。
#   这就是看图软件/照片缩放的做法：整个过程只有"一个位图 + 一个缩放+平移矩阵"，
#   没有现场重绘、没有 sprite、没有尺寸换算 ⇒
#     ① 观感**就是**图片缩放（字和图一起变大变小，比例分毫不差）；
#     ② 每帧只有一次 drawPixmap（1~2ms）⇒ 60fps 真丝滑；
#     ③ 结构上不可能"放大/错乱/整张图消失"（以前那套现场合成每帧要算
#        383 个站点的尺寸/位置/排版，任何一处算飞就是白屏或错位）。
#   松手 160ms 后照旧落真实变换 + 全量重绘 ⇒ 静止时仍是清晰的矢量图。
#   想退回老的现场合成：METROEDITOR_ZOOM_BITMAP=0。
ZOOM_BITMAP = os.environ.get("METROEDITOR_ZOOM_BITMAP", "1") != "0"

# ★ 站名"往外让圈"只在放大档启用（见 try_place 里的 sides_try）：
#   小档时让 1 圈 ≈ 53 屏幕px，已经跨过 1~2 个站距 ⇒ 文字看着跑到别的站上了。
#   （外推量本身还有 LABEL_RING_MAX_PX=26 屏幕px 的封顶，双重保险）
LABEL_RING_MIN_SCALE = float(os.environ.get("METROEDITOR_RING_MIN_SCALE", "0.20"))

# 站名防重叠排版参数
LABEL_PAD = 3.0        # 站名之间最小留白（★ v2.6.42 起是**场景单位**）
DOT_AVOID_PAD = 1.5    # 站名与"其他站点圆点"的最小留白（★ v2.6.42 起场景单位）
LABEL_CELL_MIN = 40.0  # 空间网格最小格边长（场景单位）
DRAG_THRESHOLD = 4     # 超过多少像素才算"拖动"（否则算单击）

# ★ v2.6.32：站名方位"锁死"生效的最低缩放。
#   缩放比这还小的时候，站名框（屏幕尺寸恒定）在场景里占的地盘比站距还宽，
#   排版器必须靠换边才能不叠成一坨 ⇒ 那一档维持原来的"能挪就挪"。
#   放大到这之上 ⇒ 一律用 _side_lock 里那一份（1:1 参考档算出来的）方位，
#   **永远不换边**（用户：「不要每次缩放都上下左右的乱窜」）。
# ★ v2.6.32：门槛跟 **MIN_VIEW_SCALE（最小缩放）对齐** ⇒ 程序能到的每一档
#   都用锁表 ⇒ **全缩放范围零换边**，站名彻底不"上下左右乱窜"。
#   （0.30 档的锁是 1:1 参考档算出来的：实测那一档压线 2/383、1.00 档 0/383。）
# ★★ v2.6.38：门槛**固定 0.30**，不再跟着 MIN_VIEW_SCALE 走 —— 后者已放宽到
#   0.10，而"小档被迫换边会把放大档的锁表污染"这条没变（换边是写在 _take()
#   里的）。0.10~0.30 这一小段维持"能挪就挪"，0.30 以上全锁。
LABEL_LOCK_MIN_SCALE = float(os.environ.get(
    "METROEDITOR_LABEL_LOCK_SCALE", "0.30"))
# 算锁时用的参考缩放（1:1 档 = 跟原图同一量级，也是"不压线"验收的那一档）
LABEL_LOCK_REF_SCALE = float(os.environ.get("METROEDITOR_LABEL_LOCK_REF", "1.0"))

# ★ v2.6.35：「原图对照」底图 —— 官方原图垫在地铁图下面，用来逐站对位置。
#   ★★ v2.6.36：第一版为了省内存压成了 2000×2000，结果**糊得没法对**（用户原话
#     「原图太模糊了」）—— 1 个底图像素顶 4×4 个原图像素，放大回来全靠插值。
#     实测 8000×8000 原图（7.35MB PNG）加载只要 **299ms**，
#     所以直接用原尺寸 1:1 铺，一点都不缩放 ⇒ 完全不糊。
#   ★ 只在开启底图时才加载、关掉即释放（QPixmap 随图元一起被回收）。
#   文件放 data/ 而不是 assets/：打包时只有 data/ 会被带到 exe 同级。
UNDERLAY_FILE = "underlay.png"
UNDERLAY_SCENE = 8000.0        # 底图在场景里占的范围（= 原图像素边长）
UNDERLAY_OPACITY = float(os.environ.get("METROEDITOR_UNDERLAY_OPACITY", "0.45"))

# 站名"能挤就挤"策略（两轮排版）—— 目标：缩小看全局时**尽可能把每个站的名字都显示出来**，
# 实在挤不下的（会跟别人叠在一起的）才不显示，这就是"遇堆叠则选择性显示"。
#
#   ★ 第一轮（严格）：留白 LABEL_PAD(3px)、零重叠 —— 与改动前完全一致，
#     所以"能放下就一定不放宽"，放大时的观感一点不变。
#   ★ 第二轮（兜底）：对第一轮没放下的站名，用收紧后的留白 LABEL_PAD_TIGHT(1px)
#     再试一遍，并允许压掉最多 LABEL_OVERLAP_TOL 的面积。
#     第二轮只碰"本来就显示不出来的"站名，**不会把已经放好的站名挤走或挪位**。
#   ★ 这样就没有"缩放跨过某个阈值、站名突然少几个"的跳变（试过按缩放分级，
#     在阈值两侧会出现 376→371 这种反直觉的跳变，已弃用）。
#
#   实测（真机 1480x900 → 地图像素 874x829，站名 10px，379 站）：
#     站名方向：只 4 向 / 加 4 斜角；重叠：零 / 允许压 12%
#       缩到最小 0.093：102 → 135（+斜角）→ 229（+第二轮）
#       缩放 0.16     ：233 → 295（+斜角）→ 355（+第二轮）
#       缩放 1.00     ：359 → 376（+斜角）→ 379（+第二轮）
#     ★ 第二轮之后，任何缩放级别下都**没有一个站名被压掉超过一半**
#       （实测最严重 19~27%），不会糊成一团。
LABEL_PAD_TIGHT = 1.0        # 第二轮（兜底）的站名留白（★ v2.6.42 起场景单位）
LABEL_OVERLAP_TOL = 0.12     # 第二轮允许压掉的面积比例上限（0 = 一点都不许压）
LABEL_AVOID_DOTS = True      # 站名是否必须避开"别的站点圆点"
                             # （True=现状：字不能被圆点盖住）

# ★ v2.6.9：站名必须**避开线路线条**（用户：「站名有概率显示在线路线条中，
#   理应在上下左右等其他位置，绝对不应该融入到线路的颜色线条里面」）。
#   旧排版只把站点圆点当障碍物，线路根本没进障碍表 ⇒ 一条横穿站点的线
#   会把放在"右/左"侧的站名整条压进彩色线里。
#   ★ 是**打分优选**而不是硬障碍：八个方向全压线时才选压得最少的那个，
#     绝不因为避让线路就让站名整片消失（那比压线更糟）。
LABEL_AVOID_LINES = True
LABEL_LINE_AVOID_PX = 1.5    # 站名与线路之间额外留的呼吸（屏幕像素，线宽之外）
LINE_IDX_CELL_MUL = 2.0      # 线路索引的格边长 = 排版格边长 × 这个系数

# ★ v2.6.22："约XX米"（虚线/通道上的米数）也参加防重叠排版。
#   原来它**死死钉在两端中点** ⇒ 坪山那一片三条米数
#   （坪山高铁站↔坪山 100m、未来城↔坪山广场 450m、坪山中心↔坪山中心 450m）
#   叠成一坨，还压住"站前路东 / 坪山广场"这些站名。
#   现在：摆位交给排版器，在 LINK_LABEL_SIDES 里挑一个最不打架的方向。
LINK_LABEL_AVOID = os.environ.get("METROEDITOR_NO_LINK_AVOID", "") == ""
LINK_LABEL_PAD = 2.0         # 米数与站名之间最小留白（★ v2.6.42 起场景单位）

# 浮在地图上的界面控件（右下角车厢编组等）离视口边的距离
CHROME_MARGIN = 16


class MapView(QGraphicsView):
    station_clicked = Signal(str)
    station_double_clicked = Signal(str)
    station_moved = Signal(str)
    # ★ v2.6.32：站名被单独拖过（偏移已写进 item.data，主窗口负责落盘）
    label_moved = Signal(str)
    # ★ v2.6.34：线路号方块被拖过（偏移已写进 data/badge_offsets.json）
    badge_moved = Signal(str)
    add_station_requested = Signal(QPointF)
    zoom_changed = Signal(float)
    # 单独显示某条线路的状态变化（空串 = 恢复显示全部）
    isolation_changed = Signal(str)
    # ★ v2.6.90：左键单击**空白处**（非拖动）—— 主窗口据此收起右侧详情面板
    map_empty_clicked = Signal()
    # ★ v2.7.1：空白处**右键** —— 带上全局坐标交给主窗口弹菜单
    #   （主工具栏 / 线路图例 / 详情面板 / 锁定 四类）。
    #   菜单内容属于"界面编排"，不该由地图自己决定 ⇒ 只发坐标，不在这里建菜单。
    blank_context_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)

        # ★ GPU 渲染视口：raster 软件光栅化是缩放/平移卡顿的根源
        #   （24 条抗锯齿粗线 + 758 个图元全靠 CPU 逐像素画）。
        #   换 QOpenGLWidget 后绘制合成走 GPU。无 GL 环境 / 打包缺模块 /
        #   设 METROEDITOR_GPU=0 时自动回退 CPU 模式。
        #   注意必须在 setMouseTracking 等 viewport 配置之前调用。
        self._gpu_active = self._apply_gpu_viewport()

        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.TextAntialiasing, True)
        # 缩放锚点完全由 _apply_zoom_transform 手动控制（NoAnchor），
        # AnchorUnderMouse 的自动锚定会与手动修正叠加导致内容漂移
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setBackgroundBrush(QBrush(QColor("#F7F9FB")))
        # 背景是纯色，缓存起来不必每帧重填 160 万像素
        self.setCacheMode(QGraphicsView.CacheBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        # ★ 性能：600+ 个图元，省掉每个图元绘制前后保存/恢复画笔状态的开销。
        #   我们的图元每次 paint 都会自己设好画笔/画刷，不需要 Qt 代劳。
        self.setOptimizationFlag(QGraphicsView.DontSavePainterState, True)
        self.setOptimizationFlag(QGraphicsView.DontAdjustForAntialiasing, True)
        # 图元很多，用 BSP 索引加速"这个坐标下是哪个站点"的查询
        self.scene_.setItemIndexMethod(QGraphicsScene.BspTreeIndex)

        self.scene_.setSceneRect(QRectF(0, 0, SCENE_W, SCENE_H))

        self.station_items: Dict[str, StationDotItem] = {}
        self.line_items: Dict[str, MetroLineItem] = {}
        # ★ v2.6.21：两条"官方图里有、我们原来完全没画"的东西：
        #   · link_items：虚拟换乘 / 同名双站体之间的**灰色虚线**
        #   · alt_items ：同名站点的**第二个站体**（湖贝 2号线 / 湖贝 5号线 …）
        #   数据早就写在 stations.json 里了（transfer_links / alt_bodies），
        #   但渲染端一行都没写 ⇒ 图上完全看不出来（用户：「湖贝…中间用虚线连接」
        #   「你现在和原图好多都没有对照上」）。
        self.link_items: List[DashedLinkItem] = []
        self.alt_items: Dict[str, StationDotItem] = {}
        # ★ v2.6.24：线路末端的线路号方块（key = "站@end#线号"）
        self.badge_items: Dict[str, TerminalBadgeItem] = {}
        # ★ v2.6.9：线路几何索引（站名避让线路用）+ 几何版本号。
        #   版本号只在 `rebuild_lines()` 里 +1 —— 站点拖动/保存都会走那里，
        #   于是"几何没变"的排版可以直接复用索引（收尾时排版会跑很多次）。
        self._line_idx = LineSegIndex()
        self._geom_version = 0

        # ★★ 「单独显示某条线路」的状态。
        #   注意：这里**不能用图元可见性（isVisible）当状态** —— 缩放动画期间
        #   所有站点图元会被整体 setVisible(False)（由 sprite 层代画），收尾再
        #   整体显示。若拿 isVisible 判断，一滚轮就会把藏起来的站点又放出来。
        #   所以另设一个**逻辑开关**，显隐由它统一算出来。
        self._isolated_line: str = ""
        self._isolated_stations: Optional[set] = None   # None = 不隔离（全部显示）

        # 浮在地图之上的"界面层"控件（如右下角的车厢编组卡片）。
        # 缩放动画那层合成快照每次开始都会 raise_() 盖满视口，登记在这里的
        # 控件会在快照抬层之后再抬一次，保证不被蒙住。
        self._chrome: list = []

        self._focus_station_id: str = ""
        self.add_mode: bool = False

        # ★ v2.6.81：按在**站点圆点**上的登记（松手没拖动 = 单击选中）。
        #   站名那条路走 _label_hit → mouseReleaseEvent 3744 的"没拖=选中"；
        #   圆点这条路以前松手什么都不做 ⇒ 点圆点选不中站（v2.6.55 起）。
        self._press_dot: Optional[StationDotItem] = None
        self._press_dot_pos: Optional[QPointF] = None

        # ★★ v2.7.0：🔒 拆成**两把独立的锁**（用户：右键可选「锁定轨迹」/「锁定文字」）
        #   · stations_locked —— 【锁定轨迹】站点圆点 / 副站体圆点拖不动
        #        （走 metro_render.STATIONS_LOCKED，itemChange 否决）；
        #   · labels_locked —— 【锁定文字】站名文字拖不动
        #        （走 _drag_label["locked"]，mouseMoveEvent 里跳过、松手仍可选中）。
        #   ★ 默认进来就锁「轨迹」（用户原话「每次进入软件默认锁定线路轨迹」），
        #     文字默认不锁 —— 由 MainWindow 启动时调 set_drag_locks(True, False)。
        self.stations_locked = False
        self.labels_locked = False

        # ★ v2.7.14「看图模式」：False=编辑（矢量）/ True=看图（一张位图）
        self._view_mode = False
        self._view_item = None          # 看图模式下唯一在画的图元（那张大位图）
        # ★ v2.7.18：看图模式的"悬浮命中表"。位图里没有站点信息，矢量图元又
        #   全藏了 ⇒ 圆点放大 / 气泡 / 手型光标全没了。这里在进看图模式时
        #   按**烘图基准**（PX_PER_UNIT，跟照片上那一模一样）把每站的圆点
        #   半径和站名框记下来，鼠标移动时反查 ⇒ 悬浮体验跟编辑模式一致。
        self._view_hit = []
        self._view_hover_item = None
        self._view_hover_sid = ""
        # ★ v2.7.16：左右浮层各遮住多少 px（**视口坐标**）。MainWindow 每次摆完
        #   浮层调 `set_view_insets()` 写进来（隐藏的一侧 = 0）。
        #   ⇒ 居中 / 适配一律以"没被浮层盖住的那块"为准，定位过去的站点
        #     不会正好压在面板底下（用户原话「放大/拖动以左右弹窗的边界显示」）。
        self._inset_l = 0.0
        self._inset_r = 0.0
        # ★ v2.7.20：拖动留白（= 老的 PAN_ELEMENT_PAD）改成**每实例可调**，
        #   ⚙️ 里"界面 / 地图"区块能改（用户原话「缩放可以设置边界（即左右侧的
        #   弹窗距离图中元素的距离限制）」，要放进设置里）。
        self._pan_pad_scene = PAN_ELEMENT_PAD
        self._hidden_items = []         # 看图模式下被藏起来的矢量图元（退出时还原）
        self._view_rect = None          # 位图覆盖的场景矩形
        self._lock_saved = None         # 进看图模式前两把锁的原值

        # ★★ v2.6.32：站名方位**锁死表**（station_id → 方位）。
        #   用户原话「限制文字固定在一个位置，不要每次缩放都上下左右的乱窜」。
        #   以前排版器每次重排都能换边 ⇒ 缩放跨字号档时一批站名集体跳到圆点
        #   另一侧。现在方位一旦定下来就写进这张表，之后永远不换。
        self._side_lock: Dict[str, str] = {}
        # ★ v2.6.32：正在单独拖动的站名（None = 没在拖）
        self._drag_label = None
        self._drag_label_moved = False
        # ★ v2.6.34：正在拖动的"线路号方块"（None = 没在拖）
        self._drag_badge = None
        self._drag_badge_moved = False
        # ★ v2.6.53：Ctrl + 点站点选中的两站（为"编辑这两站之间的线路"用）。
        #   只留最后点的两个：**第一个 = 基准（不动），第二个 = 被动的那个**
        #   （水平/垂直时第二个被挪到与第一个齐平）。
        self._ctrl_picks: List[str] = []
        # ★ v2.6.35：原图对照底图的图元（None = 没显示）
        self._underlay_item = None
        # ★ v2.6.38：缩放手势起点抓的整屏位图 + 位图模式专用画布
        self._snap_pix = None
        self._bmp_buf = QPixmap()
        # ★ v2.6.41：右上角「整体缩放 / 字体缩放」双滑块的状态
        self._zoom_lock = False       # 🔒 整体缩放：滚轮不再改变缩放（防误触）
        self._font_mul = 1.0          # 字号倍率
        self._font_lock_px = None     # 🔒 字体缩放：锁死在这个屏幕字号
        # 字号改动要重算 383 个站 ⇒ 拖滑块时做 80ms 防抖，不然一卡一卡的
        self._font_timer = QTimer(self)
        self._font_timer.setSingleShot(True)
        self._font_timer.setInterval(80)
        self._font_timer.timeout.connect(self._apply_font_settings)
        self.scale_panel = None

        self._scale = 1.0
        # ★ v2.6.51：左端 = MIN_VIEW_SCALE（0.115），与滚轮下限**同一个数** ⇒
        #   拖到最左就停在这儿，显示正好 1.00×，不会再冒出比 1 小的数字。
        self._zoom_min = MIN_VIEW_SCALE
        # ★ v2.7.6：上限不再写死 8.0，直接取档位表末档（面板显示 ZOOM_STEP_MAX_SHOWN）。
        #   它同时是缩放滑块的上限（下面 ScalePanel(zmin, zmax) 用的就是它）。
        self._zoom_max = ZOOM_MAX_SCALE
        self._first_fit_done = False
        # ★ v2.7.0：滚轮累积器（固定档位步进用）—— 满一格（120）走一档，
        #   触控板的小 delta 先攒着，攒够才动，且永远不会算出"随机的比例"。
        self._wheel_acc = 0.0

        # ★ v2.6.41：右上角「整体缩放 / 字体缩放」双滑块（各带一把锁）
        #   面板只管界面，状态回传靠信号；反过来由 MapView 调 set_zoom() 把
        #   当前缩放同步回滑块（滑块内部 blockSignals，不会来回打乒乓球）。
        self.scale_panel = ScalePanel(self.viewport(),
                                      self._zoom_min, self._zoom_max)
        self.scale_panel.zoom_to.connect(self._on_zoom_slider)
        self.scale_panel.zoom_locked.connect(self._on_zoom_lock)
        self.scale_panel.font_mul_to.connect(self._on_font_mul)
        self.scale_panel.font_locked.connect(self._on_font_lock)
        # ★ v2.6.51：字体倍率下限抬到 1.8 ⇒ 默认的 1.0 已经**够不着**了。
        #   不夹一下的话：面板显示被 clamp 到 1.0×（=1.8），而实际字号仍按 1.0 算
        #   ⇒ "滑块显示"和"屏幕上真的字号"对不上。这里先夹回合法区间。
        self._font_mul = min(max(self._font_mul, self.scale_panel.fmin),
                             self.scale_panel.fmax)
        self.scale_panel.set_font_mul(self._font_mul)   # ★ 滑块初始停在 1.0×
        # ★ v2.6.77：两个面板不再作为视口浮层显示 —— 由 MainWindow 把它们
        #   塞进顶部工具栏「原图对照」右侧（tb.insertWidget 会自动改父级）。

        # ★ v2.6.75：图标类别/等级开关 —— 必须建在 `_load_view_settings()`
        #   之前：读档里有 icon_visibility 键时要立刻 set_state。
        self.icon_panel = IconTogglePanel()
        self.icon_panel.visibility_changed.connect(self._on_icon_visibility)

        self._load_view_settings()      # ★ v2.6.42：读回上次设的倍率/字体锁
        self.zoom_changed.connect(self._sync_panel_zoom)

        # ★ v2.4 平滑缩放：滚轮只累积"目标缩放"，由 16ms 定时器指数逼近，
        #   告别一步 1.15 倍的"咯噔"感。滚动停止 160ms 后才做一次
        #   "全站尺寸 + 站名防重叠排版"（O(N²) 大头），动画期间零重排。
        self._zoom_target = 1.0
        self._zoom_anchor = QPointF()
        self._zoom_anim = QTimer(self)
        # ★ 10ms（~100fps）：单帧合成仅 ~7ms，16ms 定时器在 240Hz 屏上"够用但不够顺"；
        #   降到 10ms 让画面在 240Hz 屏上更细密（工作耗时决定实际帧距，不会更卡）。
        self._zoom_anim.setInterval(10)
        # ★ PreciseTimer：CoarseTimer 在 Windows 上按 15.6ms 网格量化，
        #   16ms 请求实际会在 15.6~31ms 之间抖动 → 帧速忽快忽慢 = 顿挫
        self._zoom_anim.setTimerType(Qt.PreciseTimer)
        self._zoom_anim.timeout.connect(self._zoom_step)
        self._zoom_finish = QTimer(self)
        self._zoom_finish.setSingleShot(True)
        # ★★ v2.6.29：改回 160ms。v2.6.28 为了"胶囊跟手"压到 70ms / 静止 0.07s，
        #   实测**连续滚轮会乱**：收尾刚跑到一半下一次缩放又来了，圆点/药丸尺寸
        #   用的是半路的缩放值（用户：「连续滚轮会出现混乱」「放大了圆圈还变小了」）。
        #   跟手让位于正确性 —— 160ms + 0.12s 是 v2.6.27 之前验证过的值。
        self._zoom_finish.setInterval(160)
        self._zoom_finish.timeout.connect(self._apply_station_scale_all)
        # ★ 缩放动画期间【不】隐藏站名：动画显示的是快照位图（含站名），
        #   拉伸它 = 字面意义的"图片缩放"（文字随图变糊再恢复清晰，与看图软件一致）。
        #   旧做法"先隐藏站名再抓快照"导致快照里没有文字：缩放中文字凭空消失、
        #   停手后凭空弹回 —— 这个内容跳变本身就是顿挫感的来源之一。
        # ★ 快照拉伸动画（Apple 地图式）：动画期间整个视口显示一张按锚点
        #   拉伸的快照位图（每帧一次 blit ≈ 3ms），完全跳过场景重绘
        #   （矢量粗线 + 图元缓存重建每帧 40ms+ 是真正的瓶颈）；
        #   停手收尾时一次性真实重绘恢复清晰。
        self._snap_label = QLabel(self.viewport())
        self._snap_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # ★★ 对齐必须显式钉成「左上」。QLabel 装 pixmap 的默认对齐是
        #   ［左 + 垂直居中］—— 那样"把 label 高度从底部削掉"时，pixmap 会
        #   跟着在垂直方向重新居中，露出来的**不是快照顶部而是中间一段**，
        #   整个"分条揭开"过程画面会错位。钉成左上后：
        #   label 高 rest 时，可见部分 = 快照的第 0..rest 行（顶部），
        #   真实场景从 rest 往下一整条接管 —— 这才是"从底部揭开"。
        self._snap_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # ★ 声明不透明：QLabel 默认按半透明处理，Qt 每帧都要先把标签底下的
        #   viewport（整个场景！）重绘一遍再混色标签 —— 实测多花 ~12ms/帧。
        #   我们的合成帧本身填满底色、完全 opaque，声明后 Qt 直接贴。
        self._snap_label.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._snap_label.hide()
        self._zoom_snap = None          # 活跃标志 + 快照位图（仅线路+背景层）
        self._snap_scale = 1.0
        self._snap_anchor = QPoint(0, 0)
        self._snap_anchor_scene = QPointF()   # 快照锚点对应的场景坐标
        # 看门狗标志：最后一帧动画是否画过站点 sprite（收尾白屏自愈校验用）
        self._last_snap_had_content = False
        # sprite 空闲清扫定时器：缩放收尾后分批补齐需要重建的 sprite
        # ★★ 间隔必须为 0（一有空就做一小片），而不是"每 16ms 做一批" ——
        #   见 _sprite_sweep_tick 的注释：后者会造成松手后持续一秒多的顿挫。
        self._sweep_dpr = 1.0
        self._sweep_budget = 4        # 每次做几个 sprite，按实测耗时自适应
        self._sprite_sweep = QTimer(self)
        self._sprite_sweep.setInterval(0)
        self._sprite_sweep.setTimerType(Qt.PreciseTimer)
        self._sprite_sweep.timeout.connect(self._sprite_sweep_tick)
        # 拉伸帧双缓冲：交替写入两块位图，避免"正在给 QLabel 显示的位图"
        # 被下一帧覆写造成撕裂，也避免每帧分配 5MB 新位图
        self._snap_buf = [QPixmap(), QPixmap()]
        self._snap_buf_i = 0
        # ★★ v2.5.3：手势期间"缩放 + 平移"同时进行
        #   _snap_pan 是手势期间累计的平移量（屏幕像素），直接进入合成帧的投影公式：
        #       screen = anchor + snap_pan + (scene - anchor_scene) * scale
        #   这样"边缩放边拖动"时拖动真的生效，而且**不必打断缩放动画**
        #   （以前一按左键就 _abort_zoom_snap：既做一次全场景同步重绘造成顿挫，
        #    又把刚拖出来的位移在收尾时按快照锚点覆盖掉 = 拖了白拖）。
        self._snap_pan = QPointF(0.0, 0.0)
        # ★★ v2.5.3：合成帧"是否已作废"。凡是改变画面内容的东西（缩放推进、
        #   锚点重定位、平移累加、站名排版变化）都置 True；_compose_frame 收工置 False。
        #   收尾时"分条揭开"要用它判断能不能直接沿用屏幕上的最后一帧 ——
        #   能沿用就省掉一次 15ms 的重合成，这是收尾预算里最大的一块整钱。
        self._snap_dirty = True
        # 最近一次"用户在动"（滚轮 / 拖动）的时刻。收尾那一步要做一次全场景
        # 重绘（实测 150~200ms），必须等用户停手再做，否则就落在手势中间。
        self._last_interact = 0.0
        # ★★ v2.5.3："分条揭开"—— 收尾不再一次性全屏重绘（实测 150~200ms 冻结），
        #   而是把快照按横条逐步缩小、让真实场景一条一条接管。
        #   因为这一帧合成图与真实渲染**逐像素一致**（投影公式严格对齐），
        #   每条带的"换源"用户根本看不出来，等于把一次长冻结摊成若干小步。
        self._reveal_y = 0            # 已揭开的像素高度（从底部往上）
        self._reveal_step_px = 40
        self._reveal_last = 0.0
        self._last_move_compose = 0.0   # 拖动时最后一次合帧的时刻（节流用）
        self._reveal = QTimer(self)
        self._reveal.setInterval(0)   # 尽快，但每次只揭一条
        self._reveal.setTimerType(Qt.PreciseTimer)
        self._reveal.timeout.connect(self._reveal_tick)

        # 站名防重叠排版结果：station_id -> 是否该显示
        self._auto_label: Dict[str, bool] = {}
        # 最近邻距离缓存（站点增删/移动时失效）
        self._nn_dist: Dict[str, float] = {}
        self._nn_dirty = True

        # 空白处拖动平移
        self._panning = False
        self._pan_moved = False
        self._pan_last = QPointF(0, 0)
        self._suppress_dblclick = False
        # 光标查询节流：鼠标每动 1px 都去问"这里是哪个站点"很浪费
        self._cursor_probe = QPoint(-999, -999)

        self.viewport().setMouseTracking(True)
        # ★ v2.6.12：不再是系统的 `OpenHandCursor`（那是个张开的手掌，
        #   形状大、还盖住站点），改用自己画的「圆环 + 圆心」（见 `ui/map_cursor.py`）。
        self._cursor_kind = "open"
        self.viewport().setCursor(map_cursor("open"))

        # 站点被拖动后：重算站名排版
        self.station_moved.connect(self._on_station_moved_internal)

    # ==================================================================
    # 渲染后端
    # ==================================================================
    def _apply_gpu_viewport(self) -> bool:
        """视口切 GPU（QOpenGLWidget）。默认关闭，仅 METROEDITOR_GPU=1 时启用。

        实测结论（2026-09-14）：GPU 路线三连败 ——
          ① QOpenGLWidget 与 raster 快照 QLabel 混合合成 → 缩放瞬间白屏；
          ② DeviceCoordinateCache 在 GL 下每帧全量重建纹理 → 依旧顿挫；
          ③ ItemCoordinateCache 纹理化 → 圆点消失/站名错位（diff 工具实锤）。
        而 CPU raster + 快照拉伸动画每帧仅 ~1ms，本身就是"图片缩放"模型，
        静止画面矢量重绘清晰精准。故默认走 CPU，GPU 仅留作实验开关。
        offscreen/minimal 平台（自动化测试）不支持 GL，直接回退 CPU。
        """
        import os
        if os.environ.get("METROEDITOR_GPU", "0") != "1":
            return False
        app = QApplication.instance()
        if app is not None and app.platformName() in ("offscreen", "minimal"):
            return False
        try:
            from PySide6.QtOpenGLWidgets import QOpenGLWidget
            self.setViewport(QOpenGLWidget())
            return True
        except Exception:
            return False

    # ==================================================================
    # 渲染：线路
    # ==================================================================
    def rebuild_lines(self) -> None:
        for it in self.line_items.values():
            self.scene_.removeItem(it)
        self.line_items.clear()
        # ★ v2.6.9：线路几何变了 ⇒ 站名避让用的索引作废（见 `self._line_idx`）
        self._geom_version += 1

        dm = get_data_manager()
        stations = dm.all_stations()
        through = [(d["a"], d["b"]) for d in (dm.stations_doc.get("through_links") or [])
                   if d.get("a") and d.get("b")]

        for line in dm.all_lines():
            lid = line["id"]
            seq = apply_through_links(line.get("stations") or [], through)
            if not seq:
                continue
            pts, ebl = build_line_points_ex(lid, seq, stations)
            if len(pts) < 2:
                continue
            item = MetroLineItem(lid, line.get("color", "#888888"))
            # ★ v2.6.24：折点方向照原图逐段量出来的（elbow_sides.json）
            item.set_points(pts, smooth=True, elbows=ebl)
            item.hover_callback = self._on_line_hover   # v2.6.12：悬浮线路即高亮
            self.scene_.addItem(item)
            self.line_items[lid] = item

        self._apply_line_width()
        # ★ v2.6.21：虚线/副站体跟着线路一起重建（它们贴着线路和站点）
        self.rebuild_links()
        # ★ v2.6.24：线路号方块挂在终点站上，线路/坐标一变就得重算
        self.rebuild_terminal_badges()
        # ★ 同上：线路重建后要按隔离状态把不该显示的重新藏起来，
        #   并且隔离的那条线此时已经被删掉了（例如线路被编辑/删除）→ 自动退出隔离。
        if self._isolated_line:
            if self._isolated_line in self.line_items:
                self._apply_isolation()
            else:
                self.set_isolated_line("")

    def _apply_line_width(self) -> None:
        # ★ v2.7.15：看图模式下线路图元全藏着，pen 宽度无从谈起，直接跳过。
        if getattr(self, "_view_mode", False):
            return
        for it in self.line_items.values():
            it.apply_view_scale(self._scale)
        # ★ v2.6.21：虚线也有一条"跟地图"的宽度（场景恒定 11 + 屏幕下限），
        #   缩放一变必须跟着重算；副站体同理。
        for it in self.link_items:
            it.apply_view_scale(self._scale)
        for it in self.alt_items.values():
            it.apply_view_scale(self._scale)
        # ★ v2.6.24：线路号方块同理（场景恒定 78 + 屏幕下限）
        for it in self.badge_items.values():
            it.apply_view_scale(self._scale)

    # ==================================================================
    # 渲染：线路末端的线路号方块（v2.6.24）
    # ==================================================================
    def rebuild_terminal_badges(self) -> None:
        """每条线**两端**各摆一个"线路号方块"（照原图，见 TerminalBadgeItem）。

        摆位规则本身在 `build_terminal_badge_specs()`（与对照图工具共用），
        这里只负责把它变成场景里的图元。
        """
        for it in self.badge_items.values():
            self.scene_.removeItem(it)
        self.badge_items.clear()

        dm = get_data_manager()
        specs = build_terminal_badge_specs(dm.all_stations(), dm.all_lines())
        offs = load_badge_offsets()        # ★ v2.6.34：用户拖出来的偏移
        for key, lid, x, y, ux, uy, dist, lane in specs:
            it = TerminalBadgeItem(lid, QColor(dm.line_color(lid)))
            # ★ 摆位用"相对终点站"的描述，缩放变化时由方块自己重算位置
            it.set_layout(x, y, ux, uy, dist, lane)
            it.badge_key = "%s|%s" % (lid, key)
            _o = offs.get(it.badge_key)
            if isinstance(_o, (list, tuple)) and len(_o) == 2:
                it.set_badge_off(_o[0], _o[1])
            it.apply_view_scale(self._scale)
            self.scene_.addItem(it)
            self.badge_items[key + "#" + lid] = it

        self._apply_badge_isolation()

    # ------------------------------------------------------------------
    # v2.6.35：原图对照底图（用户：「能不能把图片放到这个地铁图下面」）
    # ------------------------------------------------------------------
    def toggle_underlay(self, on: Optional[bool] = None) -> bool:
        """开关"官方原图垫底"。返回开关后的状态（True = 显示中）。

        ★ 场景坐标本来就是原图的 8000px 像素系（实测：当前站点坐标与
          `bak_relayout_20260930_021126` 的中位差只有 1.4px），
          所以底图直接铺 (0,0)-(8000,8000) 就严丝合缝，不用做任何配准。
        """
        want = (self._underlay_item is None) if on is None else bool(on)
        if want:
            self._show_underlay()
        else:
            self._hide_underlay()
        return self._underlay_item is not None

    def _show_underlay(self) -> None:
        if self._underlay_item is not None:
            return
        # ★★ 三个位置都要试（实测踩到的坑）：
        #   打包后的 exe 只在"用户数据目录还是空的"时才从 _MEIPASS 铺初始文件，
        #   老用户升级时 data/ 里已经有 stations.json，**underlay.png 就不会被
        #   复制过去**（实测 `软件/data/underlay.png` = False）⇒ 只认 DATA_DIR
        #   的话底图永远是空的。所以再兜 `_MEIPASS/data`（打包时打进去的那份）
        #   和源码目录（开发模式）。
        cands: List[Path] = []
        try:
            from core.data_manager import DATA_DIR
            cands.append(Path(DATA_DIR) / UNDERLAY_FILE)
        except (ImportError, TypeError, ValueError):
            pass
        _mei = getattr(sys, "_MEIPASS", None)
        if _mei:
            cands.append(Path(_mei) / "data" / UNDERLAY_FILE)
        cands.append(Path(__file__).resolve().parent.parent / "data" / UNDERLAY_FILE)
        pm = QPixmap()
        for p in cands:
            try:
                if p.exists():
                    pm = QPixmap(str(p))
                    if not pm.isNull():
                        break
            except (OSError, ValueError, TypeError):
                continue
        try:
            if pm.isNull():
                return
            it = QGraphicsPixmapItem(pm)
            it.setZValue(-100)                      # 垫在最底下
            it.setScale(UNDERLAY_SCENE / float(max(pm.width(), 1)))
            it.setOpacity(UNDERLAY_OPACITY)
            it.setAcceptedMouseButtons(Qt.NoButton)  # ★ 不吃鼠标，别挡操作
            it.setFlag(QGraphicsItem.ItemIsSelectable, False)
            self.scene_.addItem(it)
            self._underlay_item = it
        except (OSError, ValueError, TypeError):
            pass                                    # 没图就不显示，绝不因此崩
        self.viewport().update()

    def _hide_underlay(self) -> None:
        it = self._underlay_item
        if it is None:
            return
        self._underlay_item = None
        self.scene_.removeItem(it)
        self.viewport().update()

    def _persist_badge_offset(self, it) -> None:
        """把某个线路号方块的拖动结果写进 `data/badge_offsets.json`。

        ★ 拖回原位（偏移 ~0）就把这条**删掉**，让文件只留"真的改过"的条目，
          不至于 76 行全是 [0.0, 0.0]。
        """
        d = load_badge_offsets()
        key = getattr(it, "badge_key", "")
        if not key:
            return
        if it.has_badge_off():
            d[key] = [round(it.badge_off().x(), 1), round(it.badge_off().y(), 1)]
        else:
            d.pop(key, None)
        save_badge_offsets(d)

    def reset_badge_offsets(self) -> int:
        """把所有线路号方块复位（删掉整个叠加文件），返回复位了几个。"""
        d = load_badge_offsets()
        n = len(d)
        if n:
            save_badge_offsets({})
        self.rebuild_terminal_badges()
        return n

    def _apply_badge_isolation(self) -> None:
        """只看某条线时，别的线的线路号方块一起藏起来。"""
        lid = self._isolated_line
        for k, it in self.badge_items.items():
            own = k.rsplit("#", 1)[-1]
            it.setVisible((not lid) or own == lid)

    # ==================================================================
    # 渲染：虚拟换乘虚线 / 同名副站体（v2.6.21）
    # ==================================================================
    def rebuild_links(self) -> None:
        """重建两类"官方图里有、我们原来完全没画"的元素（幂等，可反复调用）。

        ① `transfer_links`（**不同名**的两站）：画一条灰色虚线 + 线上标米数
           —— 新澜↔观澜 50m / 坪山高铁站↔坪山 100m / 未来城↔坪山广场 450m /
              龙背↔东纵纪念馆 500m。
        ② `alt_bodies`（**同名**的两个站体，用户原话「重复显示的」）：
           在副站体坐标上再画一个站点（用所属线的颜色）+ 两者之间连虚线
           —— 湖贝(2/5)、红岭南(9/11)、清湖(4/有轨电车)、坪山中心(14/云巴)。
           有米数的（清湖 50m、坪山中心 450m）标米数；没有的（湖贝/红岭南）
           只画虚线 —— 这一点是**照原图**的：原图湖贝那条虚线上没有文字。

        ★ 与 `rebuild_lines()` 一样，几何一变就要重建；所以由 rebuild_lines 调它。
        ★ 副站体是**纯展示**的：不吃鼠标、不可拖动/选中。因为数据模型里它没有
          独立的 station_id，让它可拖动会出现"拖了却存不下来"的假象。
        """
        for it in self.link_items:
            self.scene_.removeItem(it)
        self.link_items.clear()
        for it in self.alt_items.values():
            self.scene_.removeItem(it)
        self.alt_items.clear()

        dm = get_data_manager()
        stations = dm.all_stations()
        dashes, alts = build_link_items(
            stations,
            dm.stations_doc.get("transfer_links"),
            lambda lid: QColor(dm.line_color(lid)),
            self._scale,
        )
        for it in dashes:
            self.scene_.addItem(it)
            self.link_items.append(it)
        for key, dot in alts:
            self.scene_.addItem(dot)
            self.alt_items[key] = dot

        self._invalidate_nn()
        # ★ v2.6.22：刚建出来的米数标签默认落在"中点"档，这里立刻让排版器
        #   重新挑一次方向（否则要等到下一次缩放/重载才生效）。
        if (getattr(self, "station_items", None)
                and getattr(self, "_scale", None)
                and getattr(self, "_line_idx", None) is not None):
            self._update_label_visibility()

    # ==================================================================
    # 渲染：站点
    # ==================================================================
    def reload_stations(self, stations: Dict[str, Dict]) -> None:
        # ★ v2.6.32：站点整体重建 ⇒ 站名方位锁作废重算
        self._side_lock = {}
        for sid in list(self.station_items.keys()):
            self.scene_.removeItem(self.station_items.pop(sid))

        dm = get_data_manager()
        for sid, data in stations.items():
            lines = data.get("lines") or []
            color = QColor(dm.line_color(lines[0]) if lines else "#555555")
            item = StationDotItem(sid, data, color=color)
            self.scene_.addItem(item)
            self.station_items[sid] = item

        self._invalidate_nn()
        self._apply_station_scale_all()
        self._fit_scene_to_content()
        # ★ 数据重载（保存/导入之后）时，图元是新建的，要把隔离状态重新贴上去，
        #   否则"只看这条线"会在一保存之后就悄悄失效。
        if self._isolated_line:
            self._restore_station_visibility()
            self._update_label_visibility()

    def _fit_scene_to_content(self) -> None:
        """把场景矩形收缩到实际内容范围，让地图充分利用屏幕。"""
        if not self.station_items:
            return
        xs = [it.pos().x() for it in self.station_items.values()]
        ys = [it.pos().y() for it in self.station_items.values()]
        margin = 460.0   # 留够边距，站名不至于被裁掉
        x0, x1 = min(xs) - margin, max(xs) + margin
        y0, y1 = min(ys) - margin, max(ys) + margin
        rect = QRectF(x0, y0, x1 - x0, y1 - y0)
        self._content_rect = rect
        # ★ v2.7.13：重建/重排版后元素边界变了，拖动的限度要重算
        self._elements_rect_cache = None
        # ★ sceneRect 不再写死外扩量：交给 _refresh_scene_rect 按"当前缩放下的
        #   视口尺寸"动态算 —— 固定外扩量在缩到很小时会不够用（见该函数注释）
        self._refresh_scene_rect()
        if not self._first_fit_done:
            self.fit_map()

    def update_station(self, station_id: str, data: Dict) -> None:
        item = self.station_items.get(station_id)
        if not item:
            return
        dm = get_data_manager()
        lines = data.get("lines") or []
        item._color = QColor(dm.line_color(lines[0]) if lines else "#555555")
        item.update_from_data(data)

    def remove_station(self, station_id: str) -> None:
        item = self.station_items.pop(station_id, None)
        self._side_lock.pop(station_id, None)
        if item:
            self.scene_.removeItem(item)
        self.rebuild_lines()
        self._invalidate_nn()
        self._update_label_visibility()

    # ------------------------------------------------------------------
    # v2.6.41：右上角「整体缩放 / 字体缩放」双滑块
    # ------------------------------------------------------------------
    def _sync_panel_zoom(self, s: float) -> None:
        """滚轮/适应按钮改了缩放 ⇒ 同步滑块位置（面板内部会 blockSignals）。"""
        if self.scale_panel is not None:
            self.scale_panel.set_zoom(s)

    def _on_zoom_slider(self, s: float) -> None:
        """拖"整体缩放"滑块。

        ★ 直接复用**滚轮那条链路**（位图拉伸 → 动画收敛 → 停手落盘），
          所以手感跟滚轮一模一样：拖起来丝滑，不会一卡一卡。

        ★★ v2.7.15：看图模式改走 `_view_mode_apply_zoom()`（原因见那里），
          否则拖一下滑块同样会把 383 个矢量站点放回来。
        """
        if getattr(self, "_view_mode", False):
            self._zoom_anchor = QPointF(self.viewport().rect().center())
            self._zoom_target = min(
                max(float(s), self._min_scale_for_viewport()), self._zoom_max)
            self._view_mode_apply_zoom()
            return
        if self._zoom_snap is None:
            self._zoom_anchor = QPointF(self.viewport().rect().center())
            self._begin_zoom_snap()
        else:
            self._cancel_reveal()
            self._zoom_finish.stop()
        self._zoom_target = min(
            max(float(s), self._min_scale_for_viewport()), self._zoom_max)
        self._last_interact = _perf()
        if not self._zoom_anim.isActive():
            self._zoom_anim.start()
        self._zoom_finish.start()

    def _on_zoom_lock(self, on: bool) -> None:
        """🔒 整体缩放：锁住后滚轮不再改变缩放（滑块仍可拖）。"""
        self._zoom_lock = bool(on)

    def _on_font_mul(self, m: float) -> None:
        """拖"字体缩放"滑块：在等比字号上再乘一个倍率。"""
        self._font_mul = float(m)
        # 拖倍率 = 想让字跟着变 ⇒ 自动解开"锁定"，否则两个语义打架
        if self._font_lock_px is not None:
            self._font_lock_px = None
            if self.scale_panel is not None:
                self.scale_panel.font_lock_btn().blockSignals(True)
                self.scale_panel.font_lock_btn().setChecked(False)
                self.scale_panel.font_lock_btn().blockSignals(False)
                self.scale_panel.font_lock_btn().setText("\U0001f513")
        self._font_timer.start()          # 防抖：停手 80ms 才全量重算

    def _on_font_lock(self, on: bool) -> None:
        """🔒 字体缩放：把**当前**屏幕字号钉死，之后缩放地图字不再跟着变。"""
        if on:
            self._font_lock_px = effective_font_px(self._scale) * self._font_mul
            if self.scale_panel is not None:
                self.scale_panel.show_font_px(self._font_lock_px)
        else:
            self._font_lock_px = None
            if self.scale_panel is not None:
                self.scale_panel.set_font_mul(self._font_mul)
        self._apply_font_settings()

    def _apply_font_settings(self) -> None:
        """字号设定变了 ⇒ 全部站点重算字号 + 重排（383 站，约 100ms）。"""
        self._layout_key = None           # ★ 强制重排（排版缓存 key 只认字号档）
        self._apply_station_scale_all()
        self._update_label_visibility()
        self._save_view_settings()        # ★ v2.6.42：记住，下次打开还是这个
        self.viewport().update()

    # ---------- v2.6.42：字体滑块设定的持久化 ----------
    def view_settings_file(self) -> str:
        # ★★ 必须函数内 import：打包后 DATA_DIR 才解析到 exe 同级的 data/
        #    （模块级 import 拿的是导入那一刻的值，会被测试/热重载改掉）
        from core.data_manager import DATA_DIR
        return str(Path(DATA_DIR) / "view_settings.json")

    def _load_view_settings(self) -> None:
        """启动时读回上次设的"字号倍率 / 字体锁 / 图标可见性"。"""
        try:
            with open(self.view_settings_file(), "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return
        self._font_mul = float(d.get("font_mul", 1.0) or 1.0)
        lk = d.get("font_lock_px")
        self._font_lock_px = float(lk) if lk else None
        if self.scale_panel is None:
            return
        # ★ v2.6.51：读回的旧值可能低于新的下限 1.8（比如以前存过 0.5），先夹一下
        self._font_mul = min(max(self._font_mul, self.scale_panel.fmin),
                             self.scale_panel.fmax)
        self.scale_panel.set_font_mul(self._font_mul)
        btn = self.scale_panel.font_lock_btn()
        if self._font_lock_px:
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)
            btn.setText("\U0001f512")
            self.scale_panel.show_font_px(self._font_lock_px)
        # ★ v2.6.75：图标类别/等级可见性读回（默认全开，缺键零影响）
        iv = d.get("icon_visibility") or {}
        cat_on = dict(iv.get("cat_on") or {})
        level_on = dict(iv.get("level_on") or {})
        set_tag_visibility(cat_on, level_on)
        if getattr(self, "icon_panel", None) is not None:
            self.icon_panel.set_state(cat_on, level_on)

    def _save_view_settings(self) -> None:
        """原子写（先写 .tmp 再 replace），跟 badge_offsets 一个套路。

        ★★ v2.7.33：**必须先把旧文件读进来，只覆盖自己这几个键**。
          以前这里直接 `json.dump(d, ...)` 把整个文件重写成
          `{font_mul, font_lock_px, icon_visibility}` —— 而 `view_settings.json`
          里还住着 `image_mode` 段（ask_on_exit / auto_on_start / interval_min /
          png_path / info_panel_w / pan_pad_scene，见 ui/image_mode.py）。
          用户动一次字体滑块或图标开关，看图模式那整段设置就被抹平、重启全回默认。
          `image_mode.save_settings()` 一直是"只改自己这一段"，反过来这里破了规矩。
        """
        try:
            path = self.view_settings_file()
            d = {}
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f)
                if isinstance(old, dict):
                    d = old
            except Exception:
                d = {}          # 文件不存在 / 坏了：当空的来，别把整次保存也带崩
            d["font_mul"] = self._font_mul
            d["font_lock_px"] = self._font_lock_px
            # ★ v2.6.75：图标可见性一并落盘
            if getattr(self, "icon_panel", None) is not None:
                cat_on, level_on = self.icon_panel.state()
                d["icon_visibility"] = {"cat_on": cat_on, "level_on": level_on}
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as e:      # ★ 不许静默吞：吞掉就永远查不出"为什么没记住"
            print(f"[view-settings] 写盘失败：{e!r}  path={self.view_settings_file()}")

    def _on_icon_visibility(self, cat_on, level_on) -> None:
        """图标开关面板变化：更新渲染层状态 → 刷新全部站点标签 → 落盘。"""
        set_tag_visibility(cat_on, level_on)
        for it in self.station_items.values():
            # update_from_data 会重过 filtered_tags 这道闸（签名没变不炸缓存）
            it.update_from_data(it.data)
        self._save_view_settings()

    def _apply_station_scale_all(self) -> None:
        """缩放收尾：虚拟缩放一次性落到真实变换，再统一更新尺寸/站名排版。

        ★★ v2.7.15：看图模式下**直接跳过**（实测 18ms，且看图模式根本不画
          矢量站点 —— 站名是照片上的像素）。红环半径改由 `drawForeground`
          用烘图密度自己算，不依赖这里的缓存值（见那里的注释）。

        ★★ 顺序铁律：必须先把站点尺寸/排版/ sprite 全部更新到新缩放，
        【最后】才能撤快照同步重绘 —— 否则同步重绘画出的是
        "旧尺寸图元 × 新缩放视图"：放大时文字圆点超大（错位）、
        缩小时缩成小点（看似白屏），随后才恢复 —— 正是用户报告的
        "特定阶段错位/白屏/文字大小异常后恢复"。
        """
        if getattr(self, "_view_mode", False):
            return
        if self._zoom_anim.isActive():
            self._zoom_finish.start()   # 动画未收敛：快照继续盖着，稍后再收尾
            return
        # ★★ v2.5.3：用户还在动就先别落地。
        #   落地这一步要做一次"全场景重绘"（把 500 多个图元的离屏缓存重建一遍，
        #   实测 150~200ms）。如果它落在"刚缩完接着又拖"的手势中间，就是用户
        #   报告的"缩放同时移动会卡顿"。所以：只要左键还按着、或 120ms 内还滚过
        #   轮/拖过，就把收尾再推迟一次（滚轮一来又会重置这个定时器）。
        if self._panning or (_perf() - self._last_interact) < 0.12:
            self._zoom_finish.start()
            return
        _t_all0 = _perf()
        snap_active = self._zoom_snap is not None
        if snap_active:
            # 虚拟缩放一次性落到真实变换（不触发可见重绘，快照仍盖着）
            # ★★ v2.7.6：比例按**当前真实变换**算，不再照抄 `_snap_scale`。
            #    `_snap_scale` 只是"抓快照那一刻"的缩放 —— 一旦快照没被正常释放
            #    （离屏/抓到空图走兜底路径时就会），它就成了**过期值**：
            #    真实变换明明已经 0.2817，它还记着 0.1204 ⇒ 这里又乘 2.34 倍，
            #    画面当场弹到 0.6978；再来一次就冲出上限（旧档位实测冲到 **8.728**，
            #    上限只有 8.0）。A/B 对照过：新档位、旧档位都中招 ⇒ **老毛病**。
            #    改成按真实变换算 ⇒ 这一步天然**幂等**：收尾后变换恒等于 `_scale`
            #    （ratio 算出 1.0 就直接在 `_apply_zoom_transform` 里早退）。
            #    健康路径下两者本来相等，行为分毫不差。
            _cur_tf = self.transform().m11()
            if not (_cur_tf > 1e-9) or _cur_tf != _cur_tf:
                _cur_tf = self._snap_scale
            self._apply_zoom_transform(self._scale / max(_cur_tf, 1e-6),
                                       anchor=self._snap_anchor,
                                       sync_to_snap=True)
        _t_tf = _perf()
        s = self._scale
        # ★ v2.6.41：每次全量更新都顺带把"字体缩放"滑块的设定下发一遍 ——
        #   站点图元在保存/导入/重载时会**整个重建**，新建出来的图元不认得
        #   滑块设的倍率/锁定，不下发就会"一保存字就变回默认大小"。
        _lk = getattr(self, "_font_lock_px", None)
        _mul = getattr(self, "_font_mul", 1.0)
        for it in self.station_items.values():
            it.set_font_opts(_lk, _mul)
            it.apply_view_scale(s)
        for it in self.alt_items.values():
            it.set_font_opts(_lk, _mul)
            it.apply_view_scale(s)
        _t_sz = _perf()
        # 防重叠排版只在"会改变结果"的输入变化时重算：字号档位 / 焦点 / 悬浮
        hover_id = ""
        for it in self.station_items.values():
            if it._hover:
                hover_id = it.station_id
                break
        key = (round(effective_font_px(s)), self._focus_station_id, hover_id)
        if key != getattr(self, "_layout_key", None):
            self._layout_key = key
            self._update_label_visibility()
        _t_lay = _perf()
        # 重建站点 sprite（此刻站点图元仍隐藏且快照仍盖着，重建耗时不可见）
        # ★ 不再全量重建：签名未变的 sprite 像素完全相同，重建是纯浪费
        #   （实测 379 个全量重建 = 750ms 冻结，正是"停手瞬间一卡"的根源）。
        #   改为启动空闲清扫：动画结束后按每帧少量补齐，用户无感。
        self._start_sprite_sweep()
        _t_sweep = _perf()
        if snap_active:
            # 全部就绪后才撤快照：**分条揭开**，把这次全屏重绘摊成若干小步
            self._end_zoom_snap(reveal=True)
        _t_rv = _perf()
        # ★ 性能日志：只在"确实慢"时输出（正常情况下静默），供真机诊断
        total_ms = 1000.0 * (_perf() - _t_all0)
        max_frame = getattr(self, "_w_max_frame", 0.0)
        n_frames = getattr(self, "_w_frames", 0)
        if total_ms > 40 or max_frame > 40:
            print(f"[perf] finalize {total_ms:.0f}ms  max_frame {max_frame:.0f}ms  "
                  f"frames={n_frames}  scale={self._scale:.3f}  "
                  f"vp={self.viewport().width()}x{self.viewport().height()} "
                  f"dpr={self.devicePixelRatioF():.2f}  "
                  f"| 落变换 {1000*(_t_tf-_t_all0):.0f} 尺寸 {1000*(_t_sz-_t_tf):.0f} "
                  f"排版 {1000*(_t_lay-_t_sz):.0f} 清扫 {1000*(_t_sweep-_t_lay):.0f} "
                  f"揭开准备 {1000*(_t_rv-_t_sweep):.0f}", flush=True)
        self._w_max_frame = 0.0
        self._w_frames = 0

    # ------------------------------------------------------------------
    # sprite 空闲清扫（增量重建）
    # ------------------------------------------------------------------
    def _start_sprite_sweep(self) -> None:
        """标记需要补齐 sprite，空闲时增量重建（每次少量，避免长帧）。"""
        self._sweep_dpr = self.devicePixelRatioF()
        if not self._sprite_sweep.isActive():
            self._sprite_sweep.start()

    def _sprite_sweep_tick(self) -> None:
        """空闲补齐 sprite —— 每次只做"约 3ms 的一小片"，且不留长尾。

        ★★ 为什么必须是"无间隔 + 自适应小预算"：
           一次缩放收尾后，若当前缩放处在"字号随缩放收窄"的区间（0.08~0.30），
           屏幕上所有站点的 sprite 都会过期。实测重建一个带站名的 sprite
           = **643µs**，379 个 = **224ms** —— 这块硬工作量躲不掉（字号真的变了，
           像素真的不同）。问题在于"怎么摊"：
             旧做法：每 16ms 做 8 个 → 每个 tick 阻塞 5.5ms，连续 **1.1 秒**。
                     掉帧时间轴实测：松手后 +27ms 到 +693ms 全是 12~15ms 的洞，
                     等于松手后持续一秒多的顿挫 —— 比一次性冻结更难受。
             新做法：定时器间隔 0（一有空就切一小片），每次约 3ms，
                     实测超 4ms 就减量。同样的 224ms 在 ~0.3 秒内以"看不到的小片"
                     做完，任何时刻主线程被堵都不超过约半帧。
        """
        if self._zoom_snap is not None or self._zoom_anim.isActive():
            return                      # 动画期间由逐帧预算负责，别抢时间
        # ★★ 只有"用户确实停下来了"才做 —— 清扫的定位是**给下一次手势预热**
        #   （把 sprite 提前重建好，下次缩放时合成帧就不用边画边重建）。
        #   它不是任何显示所必需的东西：真实场景走矢量绘制，不读 sprite。
        #   所以绝不该和用户抢时间。实测不加这道闸门时，松手后 1.5 秒内
        #   每 9ms 就有一次 5~8ms 的 tick（60% 占空比），用户感受到的是
        #   "松手后画面还在持续一顿一顿" —— 比一次冻结更烦人。
        #   闸门后：用户一动就停、停下 0.4 秒才继续，预热照样能完成。
        if _perf() - self._last_interact < 0.40:
            return
        dpr = getattr(self, "_sweep_dpr", 1.0) or 1.0
        budget = max(1, self._sweep_budget)
        t0 = _perf()
        for it in self.station_items.values():
            if it.sprite_stale(dpr):
                it.render_sprite(dpr)
                budget -= 1
                if budget <= 0:
                    break
        else:
            self._sprite_sweep.stop()   # 全部就绪
            self._sweep_budget = 4
            return
        spent = _perf() - t0
        # 单个 sprite 的成本差异极大（密集区站名长，一个能到 ~5ms），
        # 所以按实测耗时调量：超 6ms 就腰斩，明显偏轻才加量。
        if spent > 0.006:
            self._sweep_budget = max(1, int(self._sweep_budget * 0.5))
        elif spent < 0.0025:
            self._sweep_budget = min(10, self._sweep_budget + 2)

    # ------------------------------------------------------------------
    # 站名防重叠排版
    # ------------------------------------------------------------------
    def _invalidate_nn(self) -> None:
        self._nn_dirty = True
        self._layout_key = None   # 站点增删/移动改变重叠关系，下次收尾必须重排

    def _compute_nn(self) -> Dict[str, float]:
        """每个站点到最近邻站点的距离（场景单位）。只跟坐标有关，可缓存。

        ★ 隔离状态下只算"看得见的那批站"：不然最近邻可能是已经被藏起来的站，
          站名会白留一大片空隙。
        """
        pts = [(sid, it.pos()) for sid, it in self.station_items.items()
               if self._isolation_allows(sid)]
        n = len(pts)
        out: Dict[str, float] = {}
        for i in range(n):
            sid, p = pts[i]
            best = float("inf")
            for j in range(n):
                if i == j:
                    continue
                q = pts[j][1]
                dx = p.x() - q.x()
                dy = p.y() - q.y()
                d = dx * dx + dy * dy
                if d < best:
                    best = d
            out[sid] = best ** 0.5 if best != float("inf") else 0.0
        return out

    def _label_rank(self, it: StationDotItem) -> int:
        if it.station_id == self._focus_station_id:
            return 0          # 当前键盘/鼠标焦点，必须显示
        if it._hover:
            return 1          # 悬浮中的站
        if it.is_transfer:
            return 2          # 换乘站
        return 3              # 普通站

    def _build_side_lock(self) -> None:
        """★ v2.6.32：在 **1:1 参考档** 下跑一遍排版，把每个站的站名方位定死。

        为什么非得"跑到参考档上算"、不能"当前缩放下算完就锁"：
          站名框是**屏幕尺寸恒定**的（字号/间距都不随缩放变），所以缩得越小，
          它在场景里占的地盘越大 —— 缩到 0.18 时站名框比站距还宽，排版器被迫
          把大批站名推到外圈、换到别的方向。把那一刻的结果锁死，等放大到 1:1
          就全错了（实测 1.00 档压线会飙到 38.6%）。
        1:1 档是"文字不压线"验收的那一档（v2.6.31 实测 0/383），拿它当参考。

        做法：临时把每个站点图元切到参考缩放、把 self._scale 顶成参考值，
        跑一次正常的防重叠排版，抄下所有方位，再原样还原（视图变换不动，
        所以用户看不到这一遍）。全程只做一次（_side_lock 非空就跳过）。
        """
        if self._side_lock or getattr(self, "_in_lock_pass", False):
            return
        items = [it for it in self.station_items.values()
                 if self._isolation_allows(it.station_id)]
        items += [it for it in self.alt_items.values()
                  if self._isolation_allows(it.station_id.split("@")[0])]
        if not items:
            return
        REF = LABEL_LOCK_REF_SCALE
        saved_scale = self._scale
        saved = [(it, it._view_scale) for it in items]
        self._in_lock_pass = True
        try:
            for it in items:
                it.apply_view_scale(REF)
            self._scale = REF
            self._update_label_visibility()
            for it in items:
                self._side_lock[it.station_id] = it.label_side()
        finally:
            self._in_lock_pass = False
            self._scale = saved_scale
            for it, vs in saved:
                if abs(vs - it._view_scale) > 1e-9:
                    it.apply_view_scale(vs)

    def _update_label_visibility(self) -> None:
        """
        贪心防重叠排版：按优先级依次给每个站名找一个不与已放置站名重叠的方向。
        结果与视口位置无关（全部在场景坐标里算），所以平移不需要重排。

        优先级：焦点站 > 悬浮站 > 换乘站 > 普通站；
        同一档内，越"孤立"（离最近邻站越远）的站点越先放，让站名铺得更开。

        ★★ v2.7.15：看图模式下直接跳过 —— 实测 **128ms**，是缩放收尾里最贵的
          一块；而看图模式的站名是照片上的像素，排版结果根本用不上。
        """
        if getattr(self, "_view_mode", False):
            return
        # ★ v2.6.21：同名副站体（湖贝 2号线 / 湖贝 5号线 …）也**参战**。
        #   否则两个"湖贝"各自排版、谁也不让谁，必然叠在一起。
        #   ▸ 它们的 nn 距离拿不到（不在 station_items 里）⇒ 排到最后才放，
        #     也就是"让主站先挑位置、副站体捡剩下的方向"，正是想要的优先级。
        #   ▸ 隔离状态下只跟着主站一起显示（否则单独看一条线时，
        #     副站体的名字会孤零零冒出来，指的是另一条线上的站体）。
        alt_items = [it for it in self.alt_items.values()
                     if self._isolation_allows(it.station_id.split("@")[0])]
        items = [it for it in self.station_items.values()
                 if self._isolation_allows(it.station_id)] + alt_items
        if not items:
            self._auto_label = {}
            # ★ v2.6.22：站名一个都不显示时（隔离状态下只剩别的线），
            #   米数标签也要复位到默认档，别留上一轮的位置。
            self._declutter_link_labels(None, 0.0, 1.0 / max(self._scale, 0.01))
            return

        if self._nn_dirty:
            self._nn_dist = self._compute_nn()
            self._nn_dirty = False

        # 网格边长自适应：跟着当前标签尺寸走
        # ★ label.boundingRect() 是标签局部坐标（= 屏幕像素），必须乘 label_scale()
        #   才是场景单位 —— 本函数的 cell / pad 全部是场景单位。
        lbl_h = 1.0
        for it in items:
            lbl_h = max(lbl_h, it.label.boundingRect().height() * it.label_scale())
        k = 1.0 / max(self._scale, 0.01)
        cell = max(LABEL_CELL_MIN, lbl_h * 1.15)

        # ★ 摆放顺序：先试"当前位置"，再按 正方向 → 斜角 的顺序找空位。
        #   正方向观感最规整，斜角只在正方向都塞不下时才用得上（密集区兜底）。
        sides_try = list(LABEL_SIDES_CARDINAL) + [
            s for s in LABEL_SIDES if s not in LABEL_SIDES_CARDINAL]
        # ★ v2.6.26：再补"往外让 1~2 圈"的候选位（8 → 24）。
        #   用户原话「字体限制不允许显示在线路上」—— 原来只有 8 个位置可挑，
        #   八个方向全被线路压住时只能认了（实测 0.3 档严重压线 12.5%）。
        #   顺序 = 原位 → 1 圈 → 2 圈，所以站名平时仍然紧贴圆点。
        # ★★ v2.6.27：外圈只在**放大档**给。小档时站名框比站距还宽，往外让 1 圈
        #   ≈ 53 屏幕px = 1~2 个站距 ⇒ 字会跑到隔壁站头上（用户：「缩小到一定尺寸
        #   文字完全偏离正确位置」）。那时让位没有意义，退回 8 方向原位。
        if (os.environ.get("METROEDITOR_NO_LABEL_RING", "0") != "1"
                and self._scale >= LABEL_RING_MIN_SCALE):
            sides_try = sides_try + [s + "1" for s in sides_try] + \
                [s + "2" for s in sides_try]

        # ★★ v2.6.9：把**线路**也拉进障碍判定 —— 站名压在彩色线条里是
        #   最难读的一种重叠（用户原话：「绝对不应该融入到线路的颜色线条里面」）。
        # ★★ v2.6.21：线的"半宽"必须跟**画线时**用的是同一个公式
        #   （`line_screen_width`：场景恒定 22 + 屏幕下限 3px）。
        #   原来这里硬写 SCREEN_LINE_W(=4.6 屏幕px)，线宽改成跟地图之后
        #   会**算少**——放大时线有 22px 宽、避让只按 4.6px 算 ⇒ 站名压到线上。
        line_idx = None
        line_pad = 0.0
        if LABEL_AVOID_LINES and self.line_items:
            line_idx = self._line_idx
            line_idx.build(self.line_items, cell * LINE_IDX_CELL_MUL,
                           self._geom_version)
            line_pad = (line_screen_width(self._scale) * 0.5 + LABEL_LINE_AVOID_PX) * k

        order = sorted(
            items,
            key=lambda it: (self._label_rank(it), -self._nn_dist.get(it.station_id, 0.0)),
        )

        grid: Dict[tuple, List[tuple]] = {}   # cell -> [(rect, kind, sid)]；kind ∈ {label, dot}
        pad = LABEL_PAD            # ★ v2.6.42：改成场景单位（1:1 档观感不变）
        # 桶查找范围按**最大**留白算：第二轮会把 pad 收紧，但查找范围绝不能跟着缩小，
        # 否则漏掉隔壁格子里的障碍物 → 悄悄压在一起（"少查了"比"多查了"危险得多）。
        look_pad = LABEL_PAD       # ★ v2.6.42：同上

        def cells_of(r: QRectF):
            x0 = int((r.left() - look_pad) // cell)
            x1 = int((r.right() + look_pad) // cell)
            y0 = int((r.top() - look_pad) // cell)
            y1 = int((r.bottom() + look_pad) // cell)
            for cx in range(x0, x1 + 1):
                for cy in range(y0, y1 + 1):
                    yield (cx, cy)

        def add_rect(r: QRectF, sid: str, kind: str, extra_pad: float = 0.0) -> None:
            r = r.adjusted(-extra_pad, -extra_pad, extra_pad, extra_pad)
            for key in cells_of(r):
                grid.setdefault(key, []).append((r, kind, sid))

        # ★ 先把所有站点圆点当作"障碍物"摆进去：
        #   站名不能压在别的站点圆点上（否则字被圆点盖住，读不出来）。
        #   同属一个站点的圆点与站名不算冲突。
        dot_pad = DOT_AVOID_PAD    # ★ v2.6.42：同上
        for it in items:
            rr = it.radius() + dot_pad
            p = it.pos()
            rect = QRectF(p.x() - rr, p.y() - rr, rr * 2, rr * 2)
            for key in cells_of(rect):
                grid.setdefault(key, []).append((rect, "dot", it.station_id))

        def collides(r: QRectF, owner: str, tol: float) -> bool:
            """r 放这儿会不会跟已放好的东西冲突。tol>0 时允许压掉 tol 的面积。"""
            probe = r.adjusted(-pad, -pad, pad, pad)
            area = max(probe.width() * probe.height(), 1e-9)
            for key in cells_of(r):
                bucket = grid.get(key)
                if not bucket:
                    continue
                for other, kind, sid in bucket:
                    if sid == owner:
                        continue
                    # 允许"压住别站圆点"时，圆点障碍物整体跳过
                    if kind == "dot" and not LABEL_AVOID_DOTS:
                        continue
                    inter = probe.intersected(other)
                    if inter.isEmpty():
                        continue
                    if tol <= 0.0:
                        return True
                    if inter.width() * inter.height() > area * tol:
                        return True
            return False

        def try_place(it, tol: float) -> bool:
            """给这个站名找一个不冲突的方向；找不到返回 False（不动它）。

            ★★ v2.6.9：在"不重叠"之外再排一个**压线分**：
               0 分（完全没碰到线路）⇒ 立刻采用；
               八个方向全都压线 ⇒ 选**压得最少**的那个，而不是不显示
               —— 站名消失比压线更糟，用户要的是"尽量别压"，不是"宁可不显示"。
            """
            # ★★★ v2.6.30：**优先照抄原图方位**。
            #   用户原话「绝对照抄，原图上根本就不会重叠，你自己的问题」。
            #   站名在圆点的上/下/左/右（还是斜角）由 tools/measure_label_side.py
            #   从原图逐个量出来存进 `official_label_side`（368 站）。
            #   ⇒ 有这个值就**先试这一个方位**，干净（不撞别的站名、不压线）
            #     就直接采用，排版器不许再"挑个不挤的"把它换边 ——
            #     "文字没严格跟随站点"就是这么来的。
            #   ★★ 但**不是硬锁**：我们的线路是重新示意化排过的，跟原图不是逐段
            #     重合，所以确实有一批站按原图方位会压到线上（实测 1.00 档是
            #     38.6%，而原图自己只有 3.2%）。这些才交给下面的排版器挪一挪 ——
            #     宁可方位差一格，也不要字被线穿过。
            #   A/B：METROEDITOR_NO_LABEL_OFFICIAL=1 退回排版器挑边。
            #
            # ★★★ v2.6.32：上面那段"脏了就让排版器换边"**正是用户说的
            #   「每次缩放都上下左右的乱窜」** —— 缩放一跨字号档，碰撞/压线的
            #   判定结果就变，同一批站名会集体从左边跳到上边、再跳回来。
            #   用户原话「限制文字固定在一个位置」⇒ 改成**真硬锁**：
            #     ① 用户手动拖过站名的（label_dx/label_dy）⇒ 一个像素都不动；
            #     ② 有原图方位的 ⇒ **只认这一个方位**，压线也不换边
            #        （嫌位置不好就用"单独拖动站名"改，改完是固定值，不会自己跑）；
            #     ③ 没量到方位的 ⇒ 排版器挑一次，**挑完写进 _side_lock**，
            #        之后同样永远不变。
            if it.has_label_off():
                # ★★ v2.6.43：用户手动定过位置 ⇒ 把**当时的方位**也写进锁表。
                #   否则换到别的倍率时排版器会按锁表把它换到另一个方位，
                #   手动偏移叠上去 ⇒ 立刻"错位"（用户：「低倍率下设定了位置，
                #   高倍率下文字会错位，没有在其他倍率下记忆移动」）。
                if not self._side_lock.get(it.station_id):
                    self._side_lock[it.station_id] = it.label_side()
                add_rect(it.label_scene_rect(), it.station_id, "label")
                return True

            # ★ v2.6.32 实测：真硬锁到原图方位 ⇒ 1.00 档压线 148/383（38.6%）、
            #   0.30 档 113/383（29.5%），字形被线穿得没法看。所以锁的
            #   **不是"原图方位"，而是"1:1 参考档排版挑出来的方位"** ——
            #   那一档就是 0 压线（v2.6.31 实测 0/383），拿它当唯一答案锁死，
            #   既"位置固定"又"不压线"。
            _off = (it.data or {}).get("official_label_side") or ""
            _prefer = ""
            if os.environ.get("METROEDITOR_NO_LABEL_OFFICIAL", "0") != "1":
                _lock = self._side_lock.get(it.station_id)
                # ★ v2.6.43：原来这里卡着 `self._scale >= LABEL_LOCK_MIN_SCALE`
                #   （0.30）⇒ **0.30 以下每一档都重新挑方位**：实测同一站 0.15/0.30
                #   档是 lb、0.20 档却整个跳到 right1（差 170 场景单位）——
                #   就是用户说的"每次缩放上下左右乱窜/位置记不住"。
                #   锁表本来就是在 1:1 参考档跑出来的（跟当前档无关），
                #   所以**任何档都该用它**；"小档挑出来的方位不许写进锁表"
                #   那条限制保留在 _take() 里，不会污染。
                if _lock is None:
                    self._build_side_lock()
                    _lock = self._side_lock.get(it.station_id)
                if _lock:
                    rl = it.label_scene_rect(_lock)
                    if rl.width() > 0.1 and rl.height() > 0.1:
                        if it.label_side() != _lock:
                            it.set_label_side(_lock)
                        add_rect(rl, it.station_id, "label")
                        return True
                if _off:
                    _prefer = _off

            # ★ 稳定性优先：先试"当前这一侧"，空着就保持不动。
            #   排版会随字号档位/缩放重跑；若每次都从固定顺序重挑，
            #   会有一批站名在收尾瞬间集体换边跳到圆点另一侧（实测 30 个），
            #   看起来就是"站名突然错位"。优先保持原方向可把跳变降到最低。
            cur = it.label_side()
            best = None          # (穿过站名的线长, side, rect)
            _order = ([_prefer] if _prefer and _prefer != cur else []) + [cur]

            def _take(side: str, r) -> bool:
                """v2.6.32：挑定一个方位就**锁死**，下次重排不再重挑。

                ★ 只有"够大"的档位才记进锁表：小档排版是被迫换边的，
                  记下来会污染放大档的方位。
                """
                if it.label_side() != side:
                    it.set_label_side(side)
                if (self._scale >= LABEL_LOCK_MIN_SCALE
                        and os.environ.get("METROEDITOR_NO_LABEL_OFFICIAL", "0") != "1"):
                    self._side_lock[it.station_id] = side
                add_rect(r, it.station_id, "label")
                return True

            for side in _order + [s for s in sides_try if s not in _order]:
                r = it.label_scene_rect(side)
                if r.width() <= 0.1 or r.height() <= 0.1:
                    continue
                if collides(r, it.station_id, tol):
                    continue
                if line_idx is None:
                    return _take(side, r)
                # ★ 用"穿过站名的线有多长"打分：0 = 一点没碰到
                hits = line_idx.hit_length(r, line_pad)
                if hits <= 0.0:
                    return _take(side, r)
                if best is None or hits < best[0]:
                    best = (hits, side, r)
            if best is not None:
                _h, side, r = best
                return _take(side, r)
            return False

        auto: Dict[str, bool] = {}
        leftovers: List[StationDotItem] = []
        # 第一轮：严格（跟改动前一致，能放下就不放宽）
        for it in order:
            if try_place(it, 0.0):
                auto[it.station_id] = True
            else:
                it.set_label_side("right")
                leftovers.append(it)

        # 第二轮：兜底 —— 把留白收紧 + 允许轻微重叠，再给这些"没地方站"的站名一次机会。
        # 只动 leftovers，已放好的站名位置/方向不会被影响。
        if LABEL_OVERLAP_TOL > 0 and leftovers:
            pad = LABEL_PAD_TIGHT  # ★ v2.6.42：同上
            for it in leftovers:
                auto[it.station_id] = try_place(it, LABEL_OVERLAP_TOL)

        self._auto_label = auto
        for it in items:
            self._apply_label_visible(it)
        # ★ v2.6.22：站名都摆好之后，再给"约XX米"找位置（先让站名挑，
        #   米数是补充信息，让着站名走）。
        self._declutter_link_labels(line_idx, line_pad, k)
        # 站名显隐/换边都改了画面内容 → 屏幕上的合成帧作废
        self._snap_dirty = True

    def _declutter_link_labels(self, line_idx, line_pad: float, k: float) -> None:
        """"约XX米"的摆位入口（v2.6.22）：把场景里的料喂给模块级排版函数。

        ★ 之所以做成**模块级函数** `declutter_link_labels()` 而不是只留方法：
          对照图工具（tools/_render_check.py）不走 MapView，但必须和程序
          画出同一个结果 —— 否则"工具里看着好好的、软件里叠成一坨"。
        """
        links = [it for it in getattr(self, "link_items", []) if it.label is not None]
        shown = list(self.station_items.values()) + list(self.alt_items.values())
        declutter_link_labels(links, shown, line_idx, line_pad, LINK_LABEL_PAD)

    def _apply_label_visible(self, it: StationDotItem) -> None:
        """按排版结果 + 当前焦点/悬浮状态，决定这个站名是否显示。"""
        want = self._auto_label.get(it.station_id, True)
        if it._hover or it.station_id == self._focus_station_id:
            want = True
        if want != it.is_label_visible():
            self._snap_dirty = True     # 站名显隐变了 → 屏幕上的合成帧作废
        it.set_label_visible(want)

    def _on_station_moved_internal(self, station_id: str) -> None:
        self._invalidate_nn()
        self._update_label_visibility()

    # ==================================================================
    # 缩放 / 视图
    # ==================================================================
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            event.accept()
            return
        # ★ v2.6.41：右上角的 🔒 锁住整体缩放 ⇒ 滚轮直接不生效（防误触）。
        #   滑块本身仍可拖动，否则锁上就再也调不动了。
        if getattr(self, "_zoom_lock", False):
            event.accept()
            return
        # 累积目标缩放：★ v2.7.0 改成**固定档位**（消除"随机算出来的比例"）——
        #   累计滚轮 delta，每满一格（120）走**一档**；触控板的小 delta 攒够才走。
        #   档位表见 ZOOM_STEPS（数字 = 缩放面板显示值，★ v2.7.6 起等差 +0.5，
        #   1.00×~6.00× 共 11 档）。
        acc = float(getattr(self, "_wheel_acc", 0.0)) + float(delta)
        step = 0
        while acc >= WHEEL_STEP_UNIT:
            step += 1
            acc -= WHEEL_STEP_UNIT
        while acc <= -WHEEL_STEP_UNIT:
            step -= 1
            acc += WHEEL_STEP_UNIT
        self._wheel_acc = acc
        if step == 0:
            event.accept()          # 还没攒够一格：画面完全不动
            return
        step = max(-3, min(3, step))        # 一次给再多也只走 3 档
        idx = self._nearest_zoom_step_index(self._zoom_target) + step
        idx = max(0, min(len(ZOOM_STEPS) - 1, idx))
        new_target = ZOOM_STEPS[idx]
        # ★ v2.6.38：目标一旦算出非正数/NaN，立刻退回当前真实缩放 ——
        #   后面所有除法（ratio = target/_scale）都建立在 target>0 上。
        if not (new_target > 0.0) or new_target != new_target:
            new_target = max(self._scale, 1e-6)
        # 越界直接夹住（旧版是"到边界后滚轮完全失灵"，体验差）
        # ★ 下限不是固定的自量（_zoom_min），而是"当前视口下滚动条仍有余量"的
        #   最低缩放（_min_scale_for_viewport）。缩得比它还小 → Qt 会把滚动条
        #   range 压成 0 并强制居中 → "缩到最小再放大"锚点失效、画面跳位。
        self._zoom_target = min(max(new_target, self._min_scale_for_viewport()),
                                self._zoom_max)
        pos = event.position() if hasattr(event, "position") else QPointF(event.pos())
        self._zoom_anchor = QPointF(pos)
        # ★ v2.5.3：记下"用户在动"（收尾那一步要等用户停手再做）
        self._last_interact = _perf()
        # ★★ v2.7.15：看图模式走"照片直落"快路径。
        #   老路径是给**矢量**设计的（抓视口位图 → 拉伸 → 停手后全量重算），
        #   它的收尾会把 383 个站点图元 setVisible(True) 放回来 ⇒ 看图模式
        #   当场退化成矢量：实测帧耗时 4.7ms → 31ms，用户看到的"还是卡"就是它。
        #   看图模式没有矢量可画，直接改变换、重绘那一张位图即可（~5ms/帧）。
        if getattr(self, "_view_mode", False):
            self._view_mode_apply_zoom()
            event.accept()
            return
        if self._zoom_snap is None:
            # 首格：抓当前视口（含站名）做快照
            self._begin_zoom_snap()
        else:
            # ★ 若正在"分条揭开"，先把快照恢复成盖满视口再继续（否则只盖了一部分，
            #   没盖到的地方显示的是旧变换的真实场景 → 错位）
            self._cancel_reveal()
            # ★ 快照仍在（上轮动画刚收敛、收尾定时器未触发）：并入当前动画，
            #   绝不能重新 grab —— viewport().grab() 会把正在显示的快照 label
            #   一起抓进去，造成"快照叠快照"的二次曝光模糊
            self._zoom_finish.stop()
            # ★★ 缩放原点必须【跟着鼠标走】：手势中途把鼠标移到别处再滚，
            #    必须改以当前位置为原点，否则画面会绕着一个旧点缩放 ——
            #    表现为"内容往旁边跑、缩放不跟鼠标"（用户报告多年的错位）。
            self._retarget_snap_anchor(pos)
        if not self._zoom_anim.isActive():
            self._zoom_anim.start()   # 已活跃则不打断（重启会跟随滚轮节奏丢帧）
        # 每次滚动都重置收尾计时：停手 160ms 后才做全量尺寸/排版更新
        self._zoom_finish.start()
        event.accept()

    def _view_mode_apply_zoom(self) -> None:
        """★ v2.7.15：看图模式专用 —— 把 `_zoom_target` 一次性落到真实变换。

        为什么看图模式不能走老链路（抓位图 → 拉伸 → 停手收尾）：
          ① 老链路的收尾 `_end_zoom_snap` 会调 `_restore_station_visibility()`
             把站点图元全部放回来 ⇒ 看图模式退化成矢量（帧 4.7→31ms）；
          ② 老链路的收尾还要跑 `_update_label_visibility()`（贪心防重叠排版，
             实测 **128ms**）和 `_apply_station_scale_all()`（18ms）——
             可看图模式下站名根本不显示（它是照片上的像素），纯属白烧。
        看图模式只需要：改变换 → 重绘那一张位图（实测 ~5ms）。
        """
        tgt = getattr(self, "_zoom_target", 0.0)
        if not (tgt > 0.0) or tgt != tgt:
            return
        ratio = tgt / max(self._scale, 1e-6)
        if abs(ratio - 1.0) < 1e-6:
            return
        # 从编辑模式切过来时可能正卡在动画中：先把快照状态干净收掉
        # （收掉时不能重绘矢量 —— _restore_station_visibility 有看图模式守卫）
        if self._zoom_snap is not None:
            self._end_zoom_snap(repaint_now=False)
        self._zoom_finish.stop()
        self._apply_zoom_transform(ratio, self._zoom_anchor)
        self.viewport().update()

    # ------------------------------------------------------------------
    # 快照拉伸动画
    # ------------------------------------------------------------------
    def _begin_zoom_snap(self) -> None:
        """动画开始：转入「逐帧现场合成」模式 —— 真实视图冻结，动画帧由
        「线路矢量重绘 + 站点 sprite 贴图」两层现场合成（每帧合计 ~7ms）。

        站点图元整体隐藏：线路重绘时只画线路；站点由 sprite 层代替显示。
        """
        # ★★ v2.6.38：先抓位图，**再**隐藏站点 —— 顺序反了就会抓到一张
        #   没有站点的空图（那就是"整张图消失"）。
        #   此刻真实变换还没动，抓到的正是用户眼前这一屏。
        self._snap_pix = None
        if ZOOM_BITMAP:
            try:
                # ★★ 抓之前必须**强制重绘一次**：grab 只拷"当前后台缓冲"，
                #   而 Qt 的绘制是异步排队的 —— 若此刻视口还没真正画过
                #   （刚 fit/刚落变换/窗口刚变化），抓到的是一张**全背景空图**，
                #   接下来整个缩放手势都在拉伸一张空图 ⇒ 用户看到的
                #   "整张图消失"就发生在这里。
                self.viewport().repaint()
                QApplication.processEvents()
                self._snap_pix = self.viewport().grab()
                # ★★ v2.7.0：**抓到空图 = 整个缩放手势在拉伸一张白图**
                #   （用户报的「瞬间四周白屏」正是这个观感）。抓到空图时：
                #   ① 先再强制重绘 + 重抓一次（绝大多数是"刚绘制完还没进缓冲"）；
                #   ② 仍为空 ⇒ **放弃位图**，本次手势退回 sprite 现场合成 ——
                #      慢一点点，但画面一定正确，绝不白屏。
                if self._pixmap_looks_blank(self._snap_pix):
                    print("[zoom-blank] 快照抓到空图，强制重绘后重抓", flush=True)
                    self.viewport().repaint()
                    QApplication.processEvents()
                    self._snap_pix = self.viewport().grab()
                if self._pixmap_looks_blank(self._snap_pix):
                    print("[zoom-blank] 重抓仍为空 ⇒ 本次缩放退回现场合成（不白屏）",
                          flush=True)
                    self._snap_pix = None
            except Exception:
                self._snap_pix = None
        for it in self.station_items.values():
            it.setVisible(False)
        self._zoom_snap = True
        self._snap_scale = self._scale
        self._snap_anchor = self._zoom_anchor.toPoint()
        # ★ 新手势：平移累计量归零、可能残留的"分条揭开"收掉（快照要盖满视口）
        self._snap_pan = QPointF(0.0, 0.0)
        self._snap_dirty = True
        self._stop_reveal(full=True)
        # 锚点的场景坐标（动画帧用它把虚拟缩放投影到屏幕坐标）
        # ★★ 必须用 Qt 的权威映射 mapToScene() 反查，【不能】再手算
        #    (scroll + anchor)/scale —— 那个式子只在"滚动条有余量"时等价，
        #    一旦场景框比视口还小（缩到很小时），Qt 会强制居中，手算式与真值
        #    能差出几百像素（实测 492px），锚点从根上就错了。
        #    mapToScene 是 QGraphicsView 自己的逆变换，任何区间都严格正确。
        self._snap_anchor_scene = self.mapToScene(self._snap_anchor)
        # 抑制底层场景自动重绘（动画期间视口由快照 label 全权接管）
        self.setViewportUpdateMode(QGraphicsView.NoViewportUpdate)
        self._snap_label.setGeometry(self.viewport().rect())
        # ★ 先合成首帧、后显示：杜绝"label 已显示但还没有内容"的白色空窗
        self._update_snap_pixmap()
        self._snap_label.raise_()
        self._raise_chrome()        # 界面层（车厢编组卡片）要压在快照之上
        self._snap_label.show()

    def _retarget_snap_anchor(self, pos: QPointF) -> None:
        """手势中途鼠标移到了别处：把缩放原点改到鼠标当前位置。

        ★ 换算原理：动画期间屏幕内容是按下式投影的
              screen = anchor + (scene - anchor_scene) * _scale
          改原点时同步反算新的 anchor_scene，让【此刻屏幕上的内容】保持不动，
          否则"换原点"这个动作本身就会造成一次画面跳动。
        """
        na = pos.toPoint()
        if na == self._snap_anchor:
            return
        s1 = max(self._scale, 1e-6)
        a = self._snap_anchor
        asc = self._snap_anchor_scene
        self._snap_anchor_scene = QPointF(
            asc.x() + (na.x() - a.x()) / s1,
            asc.y() + (na.y() - a.y()) / s1,
        )
        self._snap_anchor = na
        self._snap_dirty = True     # 原点变了 → 屏幕上的旧帧作废

    def _update_snap_pixmap(self) -> None:
        """动画帧：两层现场合成 —— 线路矢量重绘 + 站点 sprite 恒定尺寸贴图。

        ① 线路按虚拟缩放【每帧矢量重绘】：线宽恒定 4.6 屏幕像素、位置精确，
           零变形（实测仅 1.3~3ms，远低于整帧预算）；
        ② 站点/站名用预渲染 sprite 以屏幕坐标恒定尺寸贴图（Google 地图
           marker 模型）：文字圆点全程清晰不变形，随缩放平滑滑动。
        投影公式与收尾真实变换严格一致 → 动画落盘画面零跳变。
        """
        if self._zoom_snap is None or not self._snap_label.isVisible():
            return
        try:
            self._compose_frame()
        except Exception:
            # ★ 兜底：绝不只是"撤掉快照"——那样站点会以【旧尺寸】继续跟随
            #   真实变换缩放，表现为"站名在缩放中渐渐飘离圆点、松手才弹回"
            #   （用户报告多年的「缩放错位」+ 每帧全场景重绘的顿挫，都源于此）。
            #   正确做法：立刻把虚拟缩放一次性落盘到真实变换并更新全部尺寸。
            import traceback
            traceback.print_exc()
            print("[zoom-fallback] 合成帧异常，执行安全收尾", flush=True)
            self._emergency_finalize()

    def _emergency_finalize(self) -> None:
        """合成层异常时的安全收尾：落真实变换 + 全量更新尺寸 + 撤快照。

        保证任何异常都不会让"旧尺寸图元 × 新缩放"的画面出现在屏幕上。
        """
        try:
            self._zoom_anim.stop()
            self._zoom_finish.stop()
            if self._zoom_snap is not None:
                self._apply_zoom_transform(self._scale / max(self._snap_scale, 1e-6),
                                           anchor=self._snap_anchor,
                                   sync_to_snap=True)
            s = self._scale
            for it in self.station_items.values():
                it.apply_view_scale(s)
            self._apply_line_width()
            self._end_zoom_snap()
            self._zoom_target = self._scale
            self._start_sprite_sweep()
        except Exception:
            import traceback
            traceback.print_exc()

    def _draw_snap_bitmap(self) -> bool:
        """v2.6.38：把"手势开始时抓的那张整屏位图"按虚拟缩放拉伸出来。

        返回 True 表示这一帧已经画好了（调用方直接返回，别再走现场合成）。

        投影跟老的现场合成**严格同一套公式**（screen = a + pan + (scene-asc)*s），
        所以收尾落真实变换时画面零跳变：
            位图是 s0 时抓的 ⇒ 位图上点 p0 对应场景 X = asc + (p0-a)/s0
            新屏幕位置        ⇒ p  = a + pan + (X-asc)*s
                                   = a + pan + (p0-a)*(s/s0)
        ⇒ 变换 = 平移(a+pan) → 缩放(s/s0) → 平移(-a)。就这么简单。
        """
        if not ZOOM_BITMAP or self._snap_pix is None or self._snap_pix.isNull():
            return False
        vp = self.viewport()
        if vp.width() <= 2 or vp.height() <= 2:
            return False
        dpr = self.devicePixelRatioF()
        want = QSize(round(vp.width() * dpr), round(vp.height() * dpr))
        if self._bmp_buf.size() != want:      # 专用缓冲，不跟老合成帧的双缓冲混
            self._bmp_buf = QPixmap(want)
        pm = self._bmp_buf
        pm.setDevicePixelRatio(dpr)
        pm.fill(self._snap_bg())
        p = QPainter(pm)
        # ★ 平滑插值 = 图片缩放的观感（不开就是马赛克）
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        a = self._snap_anchor
        k = max(self._scale, 1e-6) / max(self._snap_scale, 1e-6)
        p.translate(a.x() + self._snap_pan.x(), a.y() + self._snap_pan.y())
        p.scale(k, k)
        p.translate(-a.x(), -a.y())
        p.drawPixmap(QPointF(0.0, 0.0), self._snap_pix)
        p.end()
        self._snap_label.setGeometry(vp.rect())
        self._snap_label.setPixmap(pm)
        self._snap_label.repaint()
        self._snap_dirty = False
        self._last_snap_had_content = True
        return True

    def _snap_bg(self) -> "QColor":
        """快照画布底色（跟地图底色一致，免得拉大后露出白边）。"""
        return getattr(self, "_bg_color", QColor("#F7F9FB"))

    def _compose_frame(self) -> None:
        if self._draw_snap_bitmap():      # ★ v2.6.38：位图模式直接返回
            return
        vp = self.viewport()
        dpr = self.devicePixelRatioF()
        self._snap_buf_i ^= 1
        pm = self._snap_buf[self._snap_buf_i]
        want = QSize(round(vp.width() * dpr), round(vp.height() * dpr))
        if pm.size() != want:
            pm = QPixmap(want)
            pm.setDevicePixelRatio(dpr)
            self._snap_buf[self._snap_buf_i] = pm
        pm.fill(QColor("#F7F9FB"))
        _t0 = _perf()
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        # ★ v2.5.3：手势期间的平移量与锚点一起构成投影原点 ——
        #   "边缩放边拖动"靠的就是这一项（拖动不再是废动作）
        ax = self._snap_anchor.x() + self._snap_pan.x()
        ay = self._snap_anchor.y() + self._snap_pan.y()
        s1 = self._scale
        asc = self._snap_anchor_scene
        # ① 线路层：虚拟缩放下矢量重绘（线宽屏幕恒定，零变形）
        for lit in self.line_items.values():
            lit.apply_view_scale(s1)
        top = QPointF(asc.x() - ax / s1, asc.y() - ay / s1)
        src = QRectF(top, QSizeF(vp.width() / s1, vp.height() / s1))
        self.scene_.render(p, QRectF(vp.rect()), src)
        _t1 = _perf()
        # ② 站点/站名 sprite 层：恒定屏幕尺寸，按虚拟缩放投影位置滑动
        vw, vh = vp.width(), vp.height()
        _nmiss = 0
        _drawn = 0
        # ★ 每帧 sprite 重建预算：跨字号档位后需要重建的 sprite 分批摊到多帧，
        #   单帧额外开销封顶约一个 sprite 的十几倍（十几毫秒），避免"某一帧
        #   突然重建几百个 sprite"造成的顿挫。剩余的交由空闲清扫补齐。
        _budget = 6
        for sid, it in self.station_items.items():
            # ★ 动画期间所有站点图元都是隐藏的（由 sprite 层代画），所以这里
            #   **不能**用 isVisible() 判断，必须问隔离状态这个逻辑开关 ——
            #   否则"单独显示某条线路"时，别的线路的站点仍会被画进快照里。
            if not self._isolation_allows(sid):
                continue
            p0 = it.pos()
            x0 = ax + (p0.x() - asc.x()) * s1
            y0 = ay + (p0.y() - asc.y()) * s1
            # 先按圆点屏幕位置粗剔除（sprite 最宽 ~200px，留 320px 余量）
            if x0 > vw + 320 or y0 > vh + 320 or x0 < -320 or y0 < -320:
                continue
            # ★★ v2.6.31：圆点/药丸**矢量实时画**（按当前虚拟缩放 s1 现算尺寸）。
            #   以前它是烤进 sprite 的，而 sprite 在手势期间冻结（每帧只准重建
            #   6 个）⇒ 圆点全程停在起点的尺寸、松手才跳（用户：「先缩小再放大」）。
            # A/B（变异自检用）：METROEDITOR_GLYPH_FROZEN=1 退回"用冻结的缩放画"
            # —— 那正是 v2.6.30 的毛病，_chk_reveal_align 的大缩放档必须能抓到。
            _gs = (it._view_scale
                   if os.environ.get("METROEDITOR_GLYPH_FROZEN") == "1" else s1)
            it.draw_glyph_screen(p, x0, y0,
                                 _gs * float(os.environ.get(
                                     "METROEDITOR_GLYPH_MUL", "1.0")))
            _drawn += 1
            # 站名仍然走 sprite（只烤文字，尺寸只跟字号走，冻住可接受）
            meta = it._sprite
            if _budget > 0 and it.sprite_stale(dpr):
                it.render_sprite(dpr)      # 只在签名变化时真正重建
                _budget -= 1
                _nmiss += 1
                meta = it._sprite
            if meta is None:
                continue
            spm, _ox, _oy, baked = meta
            # ★ 位置按**当前虚拟缩放**现算：圆点变大了，字要让开同样的距离，
            #   否则收尾时字会跟着圆点一起挪一下。
            bx = it._label_box(None, s1)
            x = x0 + bx.left() * s1
            y = y0 + bx.top() * s1
            lw = spm.width() / max(spm.devicePixelRatio(), 1.0)
            lh = spm.height() / max(spm.devicePixelRatio(), 1.0)
            # ★★ 字号也别冻住：按"当前字号 / 烤制字号"缩放贴图。
            #   位图缩放会让动画期间的字略微发虚（最多 1.4 倍），但换来了
            #   "字号连续"，收尾那一步换成真实矢量文字就看不出来了。
            kt = effective_font_px(s1) / max(effective_font_px(baked), 0.01)
            x -= LABEL_SPRITE_PAD * kt
            y -= LABEL_SPRITE_PAD * kt
            lw *= kt
            lh *= kt
            if x > vw + 40 or y > vh + 40 or x + lw < -40 or y + lh < -40:
                continue
            # ★ 用 painter 变换缩放，别用 drawPixmap(QRectF, QPixmap) ——
            #   PySide6 没有那个重载（实测 TypeError 直接走 zoom-fallback）。
            p.save()
            p.translate(x, y)
            if abs(kt - 1.0) > 1e-3:
                p.scale(kt, kt)
            p.drawPixmap(QPointF(0.0, 0.0), spm)
            p.restore()
        self._last_snap_had_content = _drawn > 0
        p.end()
        _t2 = _perf()
        prof = getattr(MapView, "_prof", None)
        if prof is not None:
            prof["lines_blit"] += _t1 - _t0
            prof["sprites"] += _t2 - _t1
            prof["miss"] += _nmiss
            prof["n"] += 1
        self._snap_label.setGeometry(vp.rect())
        self._snap_label.setPixmap(pm)
        _t3 = _perf()
        self._snap_label.repaint()   # 同步绘制：帧距不受事件循环抖动影响
        self._snap_dirty = False     # 屏幕上的这一帧已是最新（收尾时可直接沿用）
        if prof is not None:
            prof["label_repaint"] += _perf() - _t3
        # 性能看门狗：记录本手势内最慢的一帧（收尾时汇总打印，仅在异常时输出）
        _frame_ms = 1000.0 * (_perf() - _t0)
        if _frame_ms > getattr(self, "_w_max_frame", 0.0):
            self._w_max_frame = _frame_ms
        self._w_frames = getattr(self, "_w_frames", 0) + 1

    def _end_zoom_snap(self, repaint_now: bool = True, reveal: bool = False) -> None:
        """动画结束：撤掉合成帧，恢复站点图元与自动重绘。

        repaint_now=True（缩放收尾）：同步真实渲染一次 —— 调用前必须已把
        站点尺寸更新到新缩放，否则画出错位/白屏帧（见 _apply_station_scale_all）。

        ★★ v2.5.3 `reveal=True`：不一次性同步重绘，改成"分条揭开"。
           为什么需要：这一次重绘要重建 500+ 个图元的离屏缓存，实测
           **150~200ms**（站名 154 个 ~110ms、圆点 379 个 ~76ms）。
           一次性做掉就是一次肉眼可见的冻结；而它偏偏总是发生在
           "刚缩完、手还在动"的时刻 —— 正是用户报告的卡顿。
           做法：保留快照（此刻它与真实渲染逐像素一致），按横条逐步缩小它，
           让真实场景一条一条接管；每条只画一小片（~10ms），用户完全无感。
           中途若用户又开始滚轮/拖动，立刻取消揭开、退回"合成帧模式"。
        """
        if self._zoom_snap is None:
            return
        if getattr(self, "_view_mode", False):
            # ★ v2.7.15：看图模式不做"分条揭开"（那是把**矢量**收尾的全屏重绘
            #   摊成小步的技巧，看图模式只有一张位图，5ms 就画完了），
            #   也不跑"白屏看门狗"（视口内容就是那张照片，没有白屏竞态）。
            reveal = False
            repaint_now = False
        if reveal and repaint_now:
            # ★★ 顺序铁律：**先**在"站点图元仍隐藏"的状态下把终帧合成好
            #   （此时 scene_.render 只画线路 → ~17ms；若先显示站点，这一次
            #   合成会退化成全场景真实渲染 = 130ms+，等于白摊），
            #   然后才显示站点、切成自动重绘、开始分条揭开。
            self._begin_reveal()
            # ★ 不能无条件 setVisible(True)：要尊重"单独显示某条线路"的隔离状态
            self._restore_station_visibility()
            self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
            return
        self._restore_station_visibility()
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self._stop_reveal(full=True)
        self._zoom_snap = None
        self._snap_pix = None          # v2.6.38：位图用完就放（7MB 级别）
        self._snap_label.hide()
        self._snap_label.setPixmap(QPixmap())
        if repaint_now:
            self.viewport().repaint()
            # ★ 看门狗（白屏自愈）：同步重绘后立刻粗采样视口内容。
            #   若上一动画帧明明画过站点、真实渲染却几乎全空白 →
            #   说明存在未知的收尾竞态，记日志并强制再重绘一次，
            #   把任何残余白屏转化为"一帧内自愈 + 可诊断"事件。
            if self._last_snap_had_content and self._viewport_looks_blank():
                print("[zoom-watchdog] 收尾重绘后视口空白，强制二次重绘", flush=True)
                self.viewport().update()
        else:
            self.viewport().update()

    # ------------------------------------------------------------------
    # 分条揭开（v2.5.3）：把收尾的全屏重绘摊成小步
    # ------------------------------------------------------------------
    def _begin_reveal(self) -> None:
        """开始分条揭开。

        ★ 调用前站点图元必须仍是**隐藏**的 —— 这样这次合成走的是便宜的
          "线路矢量 + sprite 贴图"路径（~17ms）。显示站点由调用方在合成之后做。
        """
        vp = self.viewport()
        self._stop_reveal(full=True)
        # ★ 用最终缩放再合成一帧：动画最后一帧是在"还没贴齐目标缩放"时合成的，
        #   不重合成的话，揭开到的那条带子会跟真实渲染差一点点（肉眼可见的错位）。
        #   ★ v2.5.3：但 _zoom_step 收敛时已经补过这一帧了（见那里的注释），
        #     所以这里只在"帧确实作废"时才重合成 —— 省下收尾预算里最大的一块
        #     整钱（实测 15ms），让收尾更容易压进一帧。
        if self._snap_dirty:
            self._compose_frame()
        self._snap_label.setGeometry(vp.rect())
        self._snap_label.raise_()
        self._raise_chrome()
        self._snap_label.show()
        self._reveal_y = 0
        self._reveal_step_px = max(16, vp.height() // 24)
        self._reveal_last = 0.0
        self._reveal.start()

    def _stop_reveal(self, full: bool = False) -> None:
        """停止揭开。full=True 顺带把快照恢复成盖满视口（退回合成帧模式）。"""
        if self._reveal.isActive():
            self._reveal.stop()
        self._reveal_y = 0
        if full and self._snap_label.isVisible():
            self._snap_label.setGeometry(self.viewport().rect())
            self._snap_label.raise_()
            self._raise_chrome()

    def _cancel_reveal(self) -> None:
        """用户又开始动（滚轮/拖动）→ 取消揭开、**退回合成帧模式**。

        ★ 必须把站点图元重新隐藏并把视口更新模式切回 NoViewportUpdate：
          揭开模式下它们是可见的，此时任何"整屏重绘"都会立刻重建 500+
          个图元的离屏缓存（150~200ms）。而拖动/滚轮都会触发整屏重绘，
          所以一旦用户重新开始动，就退回"合成帧"模式 —— 那一侧每帧只要 17ms。
        """
        if not self._reveal.isActive() and not self._reveal_y:
            return
        self._stop_reveal(full=True)
        if self._zoom_snap is not None:
            for it in self.station_items.values():
                it.setVisible(False)
            self.setViewportUpdateMode(QGraphicsView.NoViewportUpdate)
            self._compose_frame()      # 站点已隐藏 → 便宜
            self._last_move_compose = _perf()

    def _reveal_tick(self) -> None:
        vp = self.viewport()
        if self._zoom_snap is None or not self._snap_label.isVisible():
            self._stop_reveal()
            return
        h = vp.height()

        # 自适应步长：目标"每条 ≤10ms"。条宽越小单帧阻塞越短，但条数越多、
        # 总时长越长；实测密集区（站名大）一条能到 12~14ms ≈ 一帧，
        # 所以阈值取 12ms 就要减量，别让任何一条吃掉整整一帧。
        now = _perf()
        if self._reveal_last:
            gap = now - self._reveal_last
            if gap > 0.012:
                self._reveal_step_px = max(12, int(self._reveal_step_px * 0.7))
            elif gap < 0.006:
                self._reveal_step_px = min(max(12, h // 6),
                                           int(self._reveal_step_px * 1.3) + 4)
        self._reveal_last = now

        self._reveal_y = min(h, self._reveal_y + self._reveal_step_px)
        rest = h - self._reveal_y
        # 缩小 label 的高度 = 从底部揭开一条；Qt 只会重绘"新露出来"的那一条
        self._snap_label.setGeometry(0, 0, vp.width(), max(0, rest))
        if rest <= 0:
            self._reveal.stop()
            self._reveal_y = 0
            self._zoom_snap = None
            self._snap_pix = None      # v2.6.38：揭开这条路也要放掉位图
            self._snap_label.hide()
            self._snap_label.setPixmap(QPixmap())
            # 揭完 = 真实场景已经全屏画好，此时才做白屏看门狗
            if self._last_snap_had_content and self._viewport_looks_blank():
                print("[zoom-watchdog] 收尾重绘后视口空白，强制二次重绘", flush=True)
                self.viewport().update()

    def _pixmap_looks_blank(self, pm) -> bool:
        """★ v2.7.0：**已抓位图**的白屏自检（抓快照之后立刻用）。

        同 `_viewport_looks_blank` 的判据（非背景像素占比 < 0.5%），但作用在
        抓好的 QPixmap 上 —— 识别"抓到一张空图"这种事故：那会让整个缩放手势
        在拉伸一张白图，用户看到的就是「瞬间四周白屏」。
        按行步进采样（bytesPerLine 不一定等于 width*bpp，逐行才安全）。
        """
        try:
            if pm is None or pm.isNull():
                return True
            img = pm.toImage()
            if img.isNull():
                return False
            w, h = img.width(), img.height()
            if w < 32 or h < 32:
                return True
            rw, rh = min(320, w - 16), min(220, h - 16)
            x0, y0 = max(0, (w - rw) // 2), max(0, (h - rh) // 2)
            bpp = img.depth() // 8
            if bpp < 3:
                return False
            raw = img.constBits().tobytes()
            bpl = img.bytesPerLine()
            total = 0
            nonbg = 0
            for y in range(y0, y0 + rh, 2):
                base = y * bpl
                for x in range(x0, x0 + rw, 2):
                    i = base + x * bpp
                    if i + 2 >= len(raw):
                        continue
                    a, b, c = raw[i], raw[i + 1], raw[i + 2]
                    total += 1
                    if (abs(a - 247) > 6 or abs(b - 249) > 6 or abs(c - 251) > 6):
                        nonbg += 1
            return total > 0 and nonbg / total < 0.005
        except Exception:
            return False

    def _viewport_looks_blank(self) -> bool:
        """粗采样视口中心区域：非背景像素占比 < 0.5% 视为白屏。

        只抓中心一小块（约 320×220）并用 bytes 步进采样 —— 整幅 grab +
        逐像素 pixelColor 要 100ms+，会自己变成一次卡顿。
        """
        try:
            vp = self.viewport()
            w, h = vp.width(), vp.height()
            rw, rh = min(320, max(32, w - 16)), min(220, max(32, h - 16))
            x0, y0 = max(0, (w - rw) // 2), max(0, (h - rh) // 2)
            img = vp.grab(QRect(x0, y0, rw, rh)).toImage()
            if img.isNull():
                return False
            raw = img.constBits().tobytes()
            bpp = img.depth() // 8
            if bpp < 3:
                return False
            total = 0
            nonbg = 0
            step = bpp * 4          # 每 4 像素采一个
            for i in range(0, len(raw) - bpp, step):
                # QImage RGB/BGRA 内存顺序不定，取三通道做"接近 #F7F9FB"判定
                a, b, c = raw[i], raw[i + 1], raw[i + 2]
                total += 1
                if (abs(a - 247) > 6 or abs(b - 249) > 6 or abs(c - 251) > 6):
                    nonbg += 1
            return total > 0 and nonbg / total < 0.005
        except Exception:
            return False   # 采样本身出错绝不干扰正常流程

    def _abort_zoom_snap(self) -> None:
        """用户中途开始点击/拖拽/改窗口时：立即把虚拟缩放落到真实变换。

        不能简单回滚 —— 用户看到的是拉伸后的画面，点击命中测试和拖拽
        都必须基于"当前看到的"缩放状态。
        ★ 顺序与收尾一致：先落变换、更新尺寸，【最后】才撤快照同步重绘，
        否则重绘出的是"旧尺寸图元 × 新缩放"的错误画面（错位/白屏）。
        """
        if self._zoom_snap is None:
            return
        self._zoom_anim.stop()
        self._zoom_finish.stop()
        self._stop_reveal(full=True)
        self._apply_zoom_transform(self._scale / max(self._snap_scale, 1e-6),
                                   anchor=self._snap_anchor,
                                   sync_to_snap=True)
        s = self._scale
        for it in self.station_items.values():
            it.apply_view_scale(s)
        self._end_zoom_snap()
        self._zoom_target = self._scale
        self._snap_pan = QPointF(0.0, 0.0)
        self._zoom_finish.start()   # 稍后统一重排版/重建 sprite

    def _hide_labels_for_zoom(self) -> None:
        """（已废弃）缩放动画期间站名随快照一起显示，不再需要隐藏。"""
        return

    def _zoom_step(self) -> None:
        """动画步（★ 纯虚拟缩放）：只推进 _scale 与快照拉伸，绝不触碰真实变换。

        血泪教训：QGraphicsView.setTransform 会【无条件】触发 viewport 全量
        重绘（不受 NoViewportUpdate 控制）—— 旧做法动画每帧 self.scale() 一次
        = 每帧一次全场景重绘（缩小状态 379 站全可见时 40~50ms/帧），
        这就是真机顿挫的根源，且离线小视口测试测不出来。
        真实变换由收尾 _apply_station_scale_all 一次性落盘。
        """
        ratio = self._zoom_target / self._scale
        if abs(ratio - 1.0) < 0.0015:      # 已收敛：贴齐目标，等收尾定时器
            self._scale = self._zoom_target
            # ★★ v2.5.3：贴齐后【必须按最终缩放再合成一帧】。
            #   原来这里直接 return，屏幕上留着的最后一帧还停在"差 0.15% 缩放"
            #   的状态（锚点离中心 400px 处就偏 0.6px）。于是收尾时不得不再合成
            #   一次来补 —— 白花 15ms；若那一次补合成被省掉，分条揭开的条带
            #   又会与真实渲染对不齐。在这里补齐，两处开销一起消失。
            self._update_snap_pixmap()
            self._zoom_anim.stop()
            self._zoom_finish.start()
            return
        step = 1.0 + (ratio - 1.0) * 0.30
        if self._zoom_snap is None:
            # 无快照（合成层异常后的兜底路径）：★ 绝不逐帧缩放 —— 此时站点
            # 尺寸仍是旧的，逐帧缩放会让"站名随缩放飘离圆点"（用户说的错位）。
            # 直接一次性落到目标缩放并更新全部尺寸，宁可少一段动画。
            self._scale = self._zoom_target
            self._emergency_finalize()
            return
        self._scale *= step
        # ★★ v2.6.38：硬夹子 —— **每算完一步立刻夹回上下限**（以前只在
        #    wheelEvent 里夹"目标"，虚拟缩放这一路没人管 ⇒ 连续快滚时
        #    `_scale` 能一路跑出上下限，落到 0 附近就是"整张图消失"）。
        #   夹完目标也要跟着夹，否则下一步 ratio 又把它拽回去（"缩小反而放大"）。
        _lo = self._min_scale_for_viewport()
        _hi = self._zoom_max
        self._scale = min(max(self._scale, _lo), _hi)
        self._zoom_target = min(max(self._zoom_target, _lo), _hi)
        self._snap_dirty = True     # 缩放推进了 → 旧帧作废
        self._update_snap_pixmap()
        self.zoom_changed.emit(self._scale)

    def _apply_zoom_transform(self, ratio: float, anchor: Optional[QPointF] = None,
                              sync_to_snap: bool = False) -> None:
        """把 ratio 一次性应用到真实变换（滚动条/线宽/缩放值同步）。

        sync_to_snap=True（缩放收尾/急停）：不再按"冻结的旧视图"做增量锚点修正，
        而是【直接按动画帧的映射】设定滚动位置：
            动画帧映射 screen = a + (scene - asc) * s
            Qt 映射      scene  = (scroll + screen) / s
            ⇒ 令二者一致：scroll = asc * s - a
        这样无论手势中途鼠标怎么移动、锚点怎么换，收尾帧都严格等于动画最后一帧
        （增量公式只在"锚点全程不变"时才等价，换过锚点就会差出成百上千像素）。
        """
        if ratio <= 0 or abs(ratio - 1.0) < 1e-9:
            return
        a = anchor if anchor is not None else self._zoom_anchor
        if a.isNull():
            a = QPointF(self.viewport().rect().center())
        # 锚点可能是 QPointF（滚轮位置）或 QPoint（快照锚点），统一成 QPoint
        vp = a.toPoint() if isinstance(a, QPointF) else a
        # ★ v2.6.43：记下"缩放前锚点指着哪个场景点"，滚完条要核对有没有漂
        _want = self.mapToScene(vp) if not sync_to_snap else QPointF()
        self.scale(ratio, ratio)
        self._scale = self.transform().m11()       # 以变换矩阵为准，杜绝累积误差
        asc = self._snap_anchor_scene if sync_to_snap else None
        # ★★ 必须在 setValue 之前补足 sceneRect：滚动条 range 由 sceneRect 决定，
        #    余量不够时 setValue 会被 clamp，锚点当场漂走（"缩小到最小会错位"）。
        self._refresh_scene_rect(vp, asc)
        h = self.horizontalScrollBar()
        v = self.verticalScrollBar()
        if sync_to_snap:
            # ★ 手势期间还累计了平移（_snap_pan），落盘时要一并算进去：
            #   投影是 screen = a + pan + (scene - asc) * s，令其等于 Qt 的
            #   screen = scene * s - scroll → scroll = asc*s - a - pan
            px = self._snap_pan.x()
            py = self._snap_pan.y()
            h.setValue(round(asc.x() * self._scale - vp.x() - px))
            v.setValue(round(asc.y() * self._scale - vp.y() - py))
        else:
            # 锚点修正（先 scale 再调滚动条，此时滚动条范围已更新）。
            # 实测 QGraphicsView 映射：scene@vp = (scroll + vp) / scale，故
            #   scroll_new = scroll + (scroll + vp) * (ratio - 1)
            # 才能让锚点视口位置下的场景点缩放前后不动。
            # （错误公式 scroll += vp*(ratio-1) 漏了 scroll*(ratio-1) 项，
            #   滚动条离原点越远漂移越大 —— 表现为"内容跟着光标跑"）
            h.setValue(h.value() + round((h.value() + vp.x()) * (ratio - 1)))
            v.setValue(v.value() + round((v.value() + vp.y()) * (ratio - 1)))
            # ★★ v2.6.43：滚动条的 setValue 会被 range **clamp** ⇒ 锚点当场漂走
            #   —— 实测一路缩到下限时，视口中心从"站点质心"(3340,3752) 漂到
            #   (693,633)，那一带 0 个站点 ⇒ 画面整片空白（回归 C3 抓到 2 次）。
            #   漂了就按缩放前的锚点场景点补一次居中，代价是一次额外 setValue。
            got = self.mapToScene(vp)
            if (abs(got.x() - _want.x()) > 1.5
                    or abs(got.y() - _want.y()) > 1.5):
                self.centerOn(_want)
        # 线宽跟手更新（便宜：24 个 pen 设置）；站点尺寸/排版由收尾统一处理
        self._apply_line_width()
        self.zoom_changed.emit(self._scale)

    def _sync_zoom_state(self) -> None:
        """fit/重置/定位等"一步到位"的缩放：清掉动画与快照，防止旧状态干扰。

        repaint_now=False：fit 马上会更新站点尺寸，重绘交给其后异步完成，
        避免此处同步重绘出"旧尺寸图元 × 新变换"的错误帧。
        """
        self._zoom_target = self._scale
        if self._zoom_anim.isActive():
            self._zoom_anim.stop()
        self._zoom_finish.stop()
        if self._zoom_snap is not None:
            self._end_zoom_snap(repaint_now=False)
        self._stop_reveal()
        self._snap_pan = QPointF(0.0, 0.0)
        self._zoom_anchor = QPointF()

    # ------------------------------------------------------------------
    # 缩放下限 + sceneRect（保证"锚点永远钉得住"）
    # ------------------------------------------------------------------
    def _min_scale_for_viewport(self) -> float:
        """缩放下限 = 「整图适配」缩放 × ZOOM_OUT_BELOW_FIT。

        ★ 下限必须只依赖「内容 rect + 视口」，绝不能依赖 sceneRect ——
          sceneRect 现在是"跟着当前视口动态长"的（见 _refresh_scene_rect），
          用它反推下限会形成"缩得越小→sceneRect 越大→下限越低"的正反馈，
          把用户一路放到缩不完。
        """
        base = getattr(self, "_content_rect", None)
        vp = self.viewport()
        if base is None or base.isEmpty() or vp.width() <= 2 or vp.height() <= 2:
            return self._zoom_min
        # 与 QGraphicsView.fitInView 一致：留 2px 边距
        fit = min((vp.width() - 2) / base.width(), (vp.height() - 2) / base.height())
        # ★ v2.6.27：再加 MIN_VIEW_SCALE 这个**绝对**下限 —— 光靠 fit×0.88 的话
        #   视口越小就能缩得越小（874 宽 ⇒ 0.096），文字必然挤成一团。
        return max(self._zoom_min, fit * ZOOM_OUT_BELOW_FIT, MIN_VIEW_SCALE)

    def _refresh_scene_rect(self, anchor_vp: Optional[QPointF] = None,
                            anchor_scene: Optional[QPointF] = None) -> None:
        """重算 sceneRect：内容 rect 兜底外扩 ∪「当前视口区域外扩 ZOOM_VIEW_MARGIN 个视口」。

        ★★ 为什么必须"盖住视口"（v2.4.5 修复"缩小到最小的时候会错位"）：
          要把锚点钉在鼠标下，收尾要设 scroll = anchor_scene*scale - 鼠标位置；
          这个值能不能生效，取决于 sceneRect 在【锚点不动】的前提下是否仍完整
          覆盖视口 —— 即锚点左边要有「鼠标x」像素、右边要有「视口宽−鼠标x」像素
          的场景余量。余量不足 → setValue 被滚动条 clamp → 画面当场漂走。
          实测（1400×900，固定 pad=2500）：鼠标在 x=200 / x=1200 时缩到最小
          分别漂 18.41px / 19.35px；x=700 / x=1000 却只有 0.5px ——
          正是因为余量只够"居中那一段"，靠边就不够了。

          本函数按「当前缩放下的视口尺寸」给余量，所以：任何缩放档位余量都刚好够；
          而且高倍缩放时视口区域远小于内容，sceneRect 仍是原来的 内容±2500，
          平移到很远虚空的松垮感一点没变多。

        anchor_vp / anchor_scene：收尾时传动画帧的锚点（此刻真实变换刚落下，
        用 mapToScene 定位可见区域可能受快照影响，直接按锚点反推更准）。
        """
        # ★ v2.7.14：看图模式下 sceneRect **就是那张位图的范围**，不跟视口外扩
        #   （跟着外扩 = 滚动条 range 越拖越大 = 又能拖到全白屏，白屏的老毛病）。
        # ★★ v2.7.31：但"完全不外扩"会把 pad 和 ins 全部废掉 —— 实测（面板 520px，
        #   v2.7.30）看图模式下 pad 填 0 / 24 / 400 / 3000，内容右端**一律停在
        #   x=1212**（面板左沿 958）⇒ 内容实打实钻在面板底下，怎么填都没用。
        #   根因：要让内容退到面板左侧，视口右边界必须能到「位图右边 + 面板宽度」，
        #   而 sceneRect 锁死在位图范围时滚动条 range 根本不够 ⇒ 限制算出来的
        #   位置不存在，拖不过去。
        #   ⇒ 现在按「pad + 两侧浮层宽度」精确外扩。拖出全白的老毛病不会回来：
        #      `_pan_limit_delta` 仍然把视口夹在「元素外 ± pad」之内，四周最多
        #      各留 pad 的空白，不会无限滚进虚空。
        if getattr(self, "_view_mode", False):
            r = getattr(self, "_view_rect", None)
            if r is not None and not r.isEmpty():
                need = self._view_mode_scene_rect(QRectF(r))
                if self.scene_.sceneRect() != need:
                    self.scene_.setSceneRect(need)
            return
        base = getattr(self, "_content_rect", None)
        if base is None or base.isEmpty():
            return
        vp = self.viewport()
        s = max(self._scale, 1e-6)
        if anchor_vp is not None and anchor_scene is not None:
            vis = QRectF(anchor_scene.x() - anchor_vp.x() / s,
                         anchor_scene.y() - anchor_vp.y() / s,
                         vp.width() / s, vp.height() / s)
        else:
            vis = self.mapToScene(vp.rect()).boundingRect()
        m = ZOOM_VIEW_MARGIN * max(vp.width(), vp.height()) / s
        need = vis.adjusted(-m, -m, m, m)
        rect = base.adjusted(-SCENE_PAD, -SCENE_PAD, SCENE_PAD, SCENE_PAD).united(need)
        if self.scene_.sceneRect() != rect:
            self.scene_.setSceneRect(rect)

    def _view_mode_scene_rect(self, base: QRectF) -> QRectF:
        """看图模式的 sceneRect = 位图范围 + 每侧「pad + 该侧浮层宽度」。

        ★ v2.7.31：没有这段外扩，看图模式下 pad / 侧边面板避开一律失效
          （详见 `_refresh_scene_rect` 里的实测数据）。左右两侧各自加
          `inset / s + pad`，上下只有 pad —— 左右因此可以各自躲开各自的面板。
        """
        s = max(self._scale, 1e-6)
        pad = float(getattr(self, "_pan_pad_scene", PAN_ELEMENT_PAD) or 0.0)
        ex_l = pad + float(getattr(self, "_inset_l", 0.0) or 0.0) / s
        ex_r = pad + float(getattr(self, "_inset_r", 0.0) or 0.0) / s
        # ★ 再补 VIEW_SCENE_SLACK_PX 像素：按理论算出来的余量常常只有几像素，
        #   而 QGraphicsView 的滚动条 range 是**整数**实测过 ihm=0/0（range 被截断成
        #   没有）⇒ 差的那几步就拖不动、内容照样压在面板下。
        #   这只是把 range 撑开一点，真正的边界仍由 `_pan_limit_delta` 管着，
        #   所以不会退回"能拖到全白屏"的老毛病。
        slack = VIEW_SCENE_SLACK_PX / s
        return base.adjusted(-ex_l - slack, -pad - slack,
                             ex_r + slack, pad + slack)

    def _elements_rect(self, force: bool = False):
        """★ v2.7.13：**图上所有元素**（站点圆点/站名/线路/图标/徽标）的
        最外边界 —— 拖动的真正边界就是它。

        ★ v2.7.12 用的是 `_content_rect`（= 站点**圆心**包围盒 + 460 单位
          假边距）：圆心包围盒的四个角本来就没东西，再外扩 460 更是纯空白
          ⇒ 大倍率下拖到边就"整屏没有一个站点"（用户原话）。
        ★ `itemsBoundingRect()` 要遍历上千个图元，不能每次 mouseMove 都算：
          结果缓存起来，重建/重排版（_fit_scene_to_content）时置空。
        """
        r = getattr(self, "_elements_rect_cache", None)
        if force or r is None or r.isEmpty():
            try:
                r = self.scene_.itemsBoundingRect()
            except Exception:
                r = None
            self._elements_rect_cache = r
        return r

    # ==================================================================
    # ★ v2.7.14 看图模式（位图）
    #
    # 编辑模式：383 站 + 20 线 + 全部站名全是矢量图元，动一下全量重画 ⇒ 卡。
    # 看图模式：先把它们烘成一张大位图藏起来，只画这一张图 ⇒ 跟看图软件一样。
    # ==================================================================
    # ------------------------------------------------------------------
    # ★ v2.7.18：看图模式的悬浮命中表
    # ------------------------------------------------------------------
    def _build_view_hit(self) -> None:
        """按**烘图基准**记下每站的圆点半径 + 站名框，供看图模式悬浮反查。

        ★ 为什么必须按 PX_PER_UNIT 重算：位图是 1 场景单位 = PX_PER_UNIT 像素
          烘出来的，而 item 内部的 `_view_scale` 停在当前视图倍率（编辑模式会
          让圆点/字号在屏幕上恒定）。直接拿当前值去比对，照片上的点和命中框
          就对不上（放大后尤其明显）。这里临时把 `_view_scale` 换成烘图基准
          取一次值再换回去 —— 图元此刻是藏着的，不会有视觉副作用。
        """
        try:
            from ui.image_mode import PX_PER_UNIT
        except Exception:
            PX_PER_UNIT = 0.69
        idx = []
        for it in list(self.station_items.values()) + list(getattr(self, "alt_items", {}).values()):
            old = getattr(it, "_view_scale", None)
            try:
                if old is not None:
                    it._view_scale = PX_PER_UNIT
                rx, ry = it.screen_half()
                r = (max(rx, ry) + VIEW_HIT_PAD_PX) / max(PX_PER_UNIT, 1e-6)
                try:
                    lr = QRectF(it.label_scene_rect())
                except Exception:
                    lr = None
                idx.append((it, it.pos().x(), it.pos().y(), r, lr))
            except Exception:
                continue
            finally:
                if old is not None:
                    try:
                        it._view_scale = old
                    except Exception:
                        pass
        self._view_hit = idx

    def view_hit_station(self, scene_pos):
        """看图模式下：鼠标落在哪个站上（圆点优先，其次站名框）。

        返回站点图元（没有就 None）。383 个站线性扫一遍，单次 <0.1ms ——
        鼠标移动事件里随便调。
        """
        idx = getattr(self, "_view_hit", None)
        if not idx:
            return None
        px, py = scene_pos.x(), scene_pos.y()
        best, bd = None, None
        for it, cx, cy, r, _lr in idx:
            dx, dy = px - cx, py - cy
            d = dx * dx + dy * dy
            if d <= r * r and (bd is None or d < bd):
                best, bd = it, d
        if best is not None:
            return best
        # 圆点都没压中 ⇒ 看是不是压在谁的站名上（框重叠时取**更小的**那个框，
        # 跟编辑模式 `_label_hit()` 一个思路：小框 = 更精确的归属）
        bl, ba = None, None
        for it, cx, cy, r, lr in idx:
            if lr is None or not lr.contains(scene_pos):
                continue
            a = lr.width() * lr.height()
            if ba is None or a < ba:
                bl, ba = it, a
        return bl

    def set_view_hover(self, item) -> None:
        """看图模式下"鼠标正悬在这个站上" ⇒ 补画放大光晕。"""
        sid = "" if item is None else getattr(item, "station_id", "")
        if sid == getattr(self, "_view_hover_sid", ""):
            return
        self._view_hover_item = item
        self._view_hover_sid = sid
        self.viewport().update()

    def enter_view_mode(self, img, rect: QRectF) -> None:
        """进入看图模式：藏掉所有矢量图元，只留那张位图。

        ★ v2.7.33：区分"首次进入"和"看图模式下重新烘图后再进"（定时出图 /
          ⚙️「立即生成」都会走这条路）。只有首次进入才备份锁态与适配基准 ——
          否则第二次进时会把"我们自己刚设的 (True, True)"当成用户的原始状态存下来。
        """
        from ui.image_mode import ViewImageItem
        from PySide6.QtGui import QPixmap

        first = not self._view_mode
        self._view_rect = QRectF(rect)
        old = self._view_item
        self._view_item = ViewImageItem(QPixmap.fromImage(img), rect)
        self.scene_.addItem(self._view_item)
        self._build_view_hit()      # ★ v2.7.18：藏之前先把命中表建好
        self._hide_vector_items()
        if old is not None:
            try:
                self.scene_.removeItem(old)
            except Exception:
                pass
        # 看图模式下站点 / 文字都拖不动（用户：看图模式只能改"详细信息"里的字）
        if first:
            self._lock_saved = (self.stations_locked, self.labels_locked)
        self.stations_locked = True
        self.labels_locked = True
        self._view_mode = True
        # 拖动边界 = 位图自己的范围（复用 v2.7.13 那套"元素最外边界"逻辑）
        self._elements_rect_cache = QRectF(rect)
        if getattr(self, "_content_rect", None) is not None:
            if first:
                # ★ v2.7.33：进看图会把"适配/居中基准"临时换成位图范围，
                #   先备份，退出时还原（不然用一次看图模式后整图适配就偏了）
                self._content_rect_saved = QRectF(self._content_rect)
            self._content_rect = QRectF(rect)
        try:
            self.scene_.setSceneRect(QRectF(rect))
        except Exception:
            pass
        self.viewport().update()

    def exit_view_mode(self) -> None:
        """退出看图模式：拿掉位图，把矢量图元放回来。"""
        if self._view_item is not None:
            try:
                self.scene_.removeItem(self._view_item)
            except Exception:
                pass
            self._view_item = None
        self._restore_vector_items()
        if self._lock_saved is not None:
            # ★ v2.7.33：必须走 set_drag_locks —— 它会同步 metro_render.STATIONS_LOCKED。
            #   以前直接给两个属性赋值，模块全局还停在 True：界面显示"已解锁"，
            #   站点圆点却照样拖不动。
            self.set_drag_locks(self._lock_saved[0], self._lock_saved[1])
            self._lock_saved = None
        self._view_mode = False
        self._view_rect = None
        self._view_hit = []                   # ★ v2.7.18：命中表作废
        self._view_hover_item = None
        self._view_hover_sid = ""
        self._elements_rect_cache = None      # 让 _elements_rect 重新实量
        # ★ v2.7.33：还原被看图模式顶掉的适配基准（见 enter_view_mode）
        if getattr(self, "_content_rect_saved", "missing") != "missing":
            self._content_rect = self._content_rect_saved
            self._content_rect_saved = None
        # ★★ v2.7.15：看图模式期间把站点尺寸/站名排版/线宽这三项**全跳过了**，
        #   退出时必须补齐 —— 否则站点还停在"烘图那一刻"的尺寸，缩放档一变
        #   圆点和站名就与当前缩放对不上（看着"突然变大/变小"）。
        try:
            self._zoom_anim.stop()
            self._apply_station_scale_all()
            self._update_label_visibility()
            self._apply_line_width()
            self._restore_station_visibility()   # 顺带把隔离状态摆回正确
        except Exception as e:
            print("[view_mode] 退出时补齐矢量状态出错：", repr(e))
        self.viewport().update()

    def _hide_vector_items(self) -> None:
        """藏掉除位图外的所有图元（记住藏了谁，退出时好还原）。"""
        keep = self._view_item
        hidden = []
        try:
            for it in self.scene_.items():
                if it is keep:
                    continue
                if not it.isVisible():
                    continue
                it.setVisible(False)
                hidden.append(it)
        except Exception as e:
            print("[view_mode] 藏图元出错：", repr(e))
        self._hidden_items = hidden

    def _restore_vector_items(self) -> None:
        """把 _hide_vector_items 藏起来的图元全部放回来。"""
        for it in list(getattr(self, "_hidden_items", []) or []):
            try:
                it.setVisible(True)
            except Exception:
                pass
        self._hidden_items = []

    def drawForeground(self, painter, rect) -> None:
        """看图模式下：选中的站点在**照片上**叠一圈会闪的红环。

        ★ 为什么必须自己画：看图模式下图元全藏了，item 自己的
          `_paint_selected_ring` 根本不会被调用 ⇒ 得由视图层补画。
        ★ 站名是照片上的像素，没法单独变红 —— 所以看图模式只闪环
          （编辑模式仍是"圆点填红 + 红环闪 + 站名变红"三件套）。
        """
        super().drawForeground(painter, rect)
        if not getattr(self, "_view_mode", False):
            return
        # ★ v2.7.18：看图模式的**悬浮反馈** —— 照片上的圆点是像素，图元又藏着，
        #   item 自己的 hover 光晕永远画不出来 ⇒ 视图层照着命中表补一圈：
        #   同色半透明光晕（半径比照片上的点大几 px）+ 一道同色外环，
        #   视觉上就是"鼠标压上去，圈放大了"。半径用**照片基准**（÷PX_PER_UNIT）
        #   ⇒ 环永远贴着照片里那个点，跟着一起放大缩小。
        hv = getattr(self, "_view_hover_item", None)
        if hv is not None and getattr(hv, "station_id", "") != getattr(
                self, "_focus_station_id", ""):
            try:
                from ui.image_mode import PX_PER_UNIT as _PPU
            except Exception:
                _PPU = 0.69
            from PySide6.QtGui import QBrush, QColor, QPen as _QPen
            hr = hx = hy = None
            for _it, _cx, _cy, _r, _lr in getattr(self, "_view_hit", []) or []:
                if _it is hv:
                    hr, hx, hy = _r, _cx, _cy
                    break
            if hr is not None:
                col = QColor(getattr(hv, "_color", "#E01010"))
                g = QColor(col)
                g.setAlpha(70)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(g))
                painter.drawEllipse(QPointF(hx, hy), hr + 2.0 / _PPU, hr + 2.0 / _PPU)
                pen = _QPen(col)
                pen.setWidthF(2.0 / _PPU)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(hx, hy), hr + 4.0 / _PPU, hr + 4.0 / _PPU)
        sid = getattr(self, "_focus_station_id", "")
        if not sid:
            return
        if getattr(self, "_blink_state", False):
            return                      # 闪烁的"灭"半周
        it = self.station_items.get(sid)
        if it is None:
            return
        try:
            from ui.metro_render import RING_OFF_PX, RING_W_PX, SELECTED_FILL
        except Exception:
            RING_OFF_PX, RING_W_PX, SELECTED_FILL = 5.0, 2.5, "#E01010"
        s = max(self._scale, 1e-6)
        try:
            r0x, r0y = it.screen_half()
        except Exception:
            r0x, r0y = 8.0, 8.0
        # ★★ v2.7.15：看图模式下 `screen_half()` 返回的是**烘图那一刻**的
        #   屏幕像素半径（因为看图模式跳过了 _apply_station_scale_all，
        #   item 内部缓存的 _view_scale 还停在烘图用的 PX_PER_UNIT）。
        #   照片里 1 个场景单位 = PX_PER_UNIT 像素 ⇒ 圆点在照片中占
        #   r0 / PX_PER_UNIT 个场景单位 —— 这样红环才会跟着照片一起放大缩小，
        #   永远贴住照片上的那个圆点（写成 r0/s 就会"放大后环比点小"）。
        try:
            from ui.image_mode import PX_PER_UNIT
        except Exception:
            PX_PER_UNIT = 0.69
        rx, ry = r0x / PX_PER_UNIT, r0y / PX_PER_UNIT
        from PySide6.QtGui import QPen, QColor
        pen = QPen(QColor(SELECTED_FILL))
        pen.setWidthF(max(1.0 / s, RING_W_PX / s))   # 线宽：屏幕恒定
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        off = RING_OFF_PX / s                        # 间隙：屏幕恒定
        p = it.pos()
        painter.drawEllipse(p, rx + off, ry + off)

    def set_pan_pad(self, pad) -> None:
        """★ v2.7.20：设"拖动余量"（场景单位）—— ⚙️ 里可调。

        ★★ v2.7.31 纠正语义：这是**保护距离**，不是放开程度。
           `_pan_limit_delta` 里可见区边界被限制在 [元素外 − pad, 元素外 + pad]，
           落到画面上就是：pad 越大 ⇒ 元素离画面边缘 / 侧边面板**越远**（越保守）；
           0 = 元素最多能贴到面板边缘。之前 v2.7.29 的注释写反了。
        """
        try:
            self._pan_pad_scene = max(0.0, float(pad))
        except Exception:
            self._pan_pad_scene = PAN_ELEMENT_PAD
        # ★ v2.7.31：看图模式的 sceneRect 要按 pad 外扩才拖得动 ⇒ 换值就重算
        try:
            self._refresh_scene_rect()
        except Exception as e:
            print("[view] 刷新 sceneRect 失败：", repr(e))

    def pan_pad(self) -> float:
        return float(getattr(self, "_pan_pad_scene", PAN_ELEMENT_PAD) or 0.0)

    def _pan_limit_delta(self, delta) -> QPointF:
        """★ v2.7.13：把一次拖动的位移夹到"元素最外边界 + 一点空白"之内。

        判据（用户原话）：「以图中所有元素最边界为限制，比如一个元素在最右
        侧，鼠标从右往左拖动，屏幕右侧的边界就是最右侧的这个元素（可适当
        保留一点空白）」。
          ⇒ 拖动后，**视口的四条边**都不得越过「元素边界 ± PAN_ELEMENT_PAD」。
          ⇒ 视口本身比内容还大（缩到很小）时无法同时满足两侧 ⇒ 直接居中。

        ★ 手势期间（缩放动画中拖动）真实变换还没落下，位移记在 _snap_pan 上，
          这里要把 _snap_pan 折算回场景坐标一起算，否则会算漏一半。
        """
        base = self._elements_rect()
        vp = self.viewport()
        if base is None or base.isEmpty() or vp.width() <= 2 or vp.height() <= 2:
            return QPointF(delta)
        s = max(self._scale, 1e-6)
        c = self.mapToScene(QPoint(vp.width() // 2, vp.height() // 2))
        cx, cy = c.x(), c.y()
        sp = getattr(self, "_snap_pan", None)
        if sp is not None:
            cx -= sp.x() / s
            cy -= sp.y() / s
        vw = vp.width() / s
        vh = vp.height() / s
        cur_l = cx - vw / 2.0     # 当前视口左边界（场景坐标）
        cur_t = cy - vh / 2.0     # 当前视口上边界
        new_l = cur_l - delta.x() / s
        new_t = cur_t - delta.y() / s

        pad = float(getattr(self, "_pan_pad_scene", PAN_ELEMENT_PAD) or 0.0)
        lo_x, hi_x = base.left() - pad, base.right() + pad
        lo_y, hi_y = base.top() - pad, base.bottom() + pad

        # ★★ v2.7.29：以前这里比的是**整个视口** vw —— 于是元素可以被一直拖到
        #   窗口边缘，而窗口右边那一条正好被「站点详情」面板压着 ⇒ 用户看到的
        #   就是"站点跑到面板底下看不见"（用户原话：「拖动留白设置成 400 依旧
        #   会被覆盖很多范围」—— 真正覆盖它的不是余量，是面板本身）。
        #   现在改成：限制作用在**可见区**上（左/右各扣掉那侧浮层盖住的宽度），
        #   余量 pad 是在可见区两侧**再**多放开的那点儿。
        #   ⇒ 左右因此天然分开（左侧是线路面板 / 右侧是详情面板），不必两个数字。
        #   ★★ v2.7.31 纠正语义：pad 是**保护距离**（越大元素离边越远），不是放开量。
        #      落到画面上：可见区里元素与会见到边缘保持 ≥ pad 的距离。
        ins_l = float(getattr(self, "_inset_l", 0.0) or 0.0) / s
        ins_r = float(getattr(self, "_inset_r", 0.0) or 0.0) / s
        # 面板极宽时可见区别被算成负数（那就整体居中不稳）
        avw = max(vw - ins_l - ins_r, 1.0)
        cur_vl = cur_l + ins_l            # 当前**可见区**左边界（场景坐标）
        new_vl = new_l + ins_l

        if hi_x - lo_x < avw:      # 可见区比内容还宽 ⇒ 居中（两侧不可能同时贴边）
            tgt_vl = lo_x + (hi_x - lo_x - avw) / 2.0
        else:
            tgt_vl = min(max(new_vl, lo_x), hi_x - avw)
        tgt_l = tgt_vl - ins_l            # 由可见区左边界还原成视口左边界
        if hi_y - lo_y < vh:
            tgt_t = lo_y + (hi_y - lo_y - vh) / 2.0
        else:
            tgt_t = min(max(new_t, lo_y), hi_y - vh)
        return QPointF((cur_l - tgt_l) * s, (cur_t - tgt_t) * s)

    def _enforce_zoom_floor(self) -> bool:
        """视口变大后（拉窗口/进全屏）当前缩放可能已跌破下限 —— 抬回下限，
        并保持"画面中心那一块"不动（不能把用户的视野顶跑）。

        返回是否真的抬过，调用方据此决定要不要跟着更新线宽/站点尺寸。
        """
        floor = self._min_scale_for_viewport()
        if self._scale >= floor - 1e-6:
            self._refresh_scene_rect()
            return False
        center = self.mapToScene(self.viewport().rect().center())
        ratio = floor / max(self._scale, 1e-9)
        self.scale(ratio, ratio)
        self._scale = self.transform().m11()
        self._refresh_scene_rect()
        self.centerOn(center)
        self._zoom_target = self._scale
        return True

    # ------------------------------------------------------------------
    # ★ v2.7.16：可见区（扣除左右浮层）—— 居中 / 适配都用它
    # ------------------------------------------------------------------
    def set_view_insets(self, left: float, right: float) -> None:
        """MainWindow 摆完浮层后调用：告诉地图左右各被遮住多少 px。

        ★ 传的是**视口像素**（不是场景单位）—— 浮层是屏幕上的东西，
          缩放一变它遮住的场景范围就变，但遮住的像素数不变。
        """
        l = max(0.0, float(left or 0.0))
        r = max(0.0, float(right or 0.0))
        if abs(l - self._inset_l) < 0.5 and abs(r - self._inset_r) < 0.5:
            return
        self._inset_l = l
        self._inset_r = r
        # ★ v2.7.31：面板宽度变了 ⇒ 看图模式的 sceneRect 也得跟着变，
        #   否则"内容退到面板左侧"所需的滚动余量不够，拖不出去。
        try:
            self._refresh_scene_rect()
        except Exception as e:
            print("[view] 刷新 sceneRect 失败：", repr(e))

    def visible_viewport_rect(self):
        """未被浮层盖住的那块视口（QRect，视口坐标）。"""
        vp = self.viewport()
        w = vp.width()
        l = min(self._inset_l, max(w - 1.0, 0.0))
        r = min(self._inset_r, max(w - l - 1.0, 0.0))
        return QRect(int(l), 0, max(int(w - l - r), 1), vp.height())

    def center_on_visible(self, p) -> None:
        """把场景点 p 摆到**可见区正中**（不是整块视口正中）。

        ★ 为什么不能直接 centerOn(p)：centerOn 把 p 放到**视口中心**，
          而视口中心在两块浮层之间未必是"看得见的正中" —— 右面板很宽时，
          视口中心那一列像素可能压在面板底下，定位过去的站就看不见了。
        """
        vp = self.viewport()
        vis = self.visible_viewport_rect()
        s = max(self._scale, 1e-6)
        dx = (vp.width() / 2.0 - vis.center().x()) / s     # 视口中心 → 可见区中心
        self.centerOn(QPointF(p.x() + dx, p.y()))

    def _station_centroid(self) -> Optional[QPointF]:
        """站点分布的**中位**位置（不是几何中心）。

        ★ v2.6.43：最小缩放 = 1.0 之后，"整图适配"实际已经适配不了（视口只够
          看全图的 6.6%），居中点选错就是一片空白 —— 内容矩形的几何中心实测
          墨迹占比 0.00%。取中位点 ⇒ 保证落在站点密集处。
        ★ 用中位数而不是平均数：几条跑到很远的远郊线（坪山/大鹏方向）会把
          平均数拖偏，中位点稳。
        """
        pts = [(it.pos().x(), it.pos().y())
               for it in self.station_items.values()]
        if not pts:
            return None
        xs = sorted(p[0] for p in pts)
        ys = sorted(p[1] for p in pts)
        n = len(xs)
        mx = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0
        my = ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2.0
        return QPointF(mx, my)

    def fit_map(self) -> None:
        # 只适配"内容 rect"（sceneRect 会外扩，直接 fit 会偏小）
        target = getattr(self, "_content_rect", None) or self.scene_.sceneRect()
        vp = self.viewport()
        # ★★ v2.6.32：**一步缩到位**，不许"先缩到整图适配、再被下限抬回去"。
        #   旧写法 = fitInView(缩到 0.109) + _enforce_zoom_floor(抬回 0.30)
        #   ⇒ 用户眼里就是"画面先缩小、再自己弹大一下"（v2.6.31 那条
        #     「为什么现在会先缩小再放大」的同一个毛病，只是发生在"适应"按钮上）。
        floor = self._min_scale_for_viewport()
        # ★ v2.7.16：按**可见区**（扣掉左右浮层）算适配比例，别让"整图适配"
        #   适配出一整张图、结果两边被面板压掉。
        vis = self.visible_viewport_rect()
        fit = min((vis.width() - 2) / max(target.width(), 1e-6),
                  (vis.height() - 2) / max(target.height(), 1e-6))
        want = max(fit, floor)           # 极端扁/窄窗口下也不会低于下限
        ratio = want / max(self._scale, 1e-9)
        self.scale(ratio, ratio)
        self._scale = self.transform().m11()
        self._sync_zoom_state()          # 先清动画/快照，再做尺寸更新
        # 其中 _refresh_scene_rect 会按新的缩放重算 sceneRect（锚点才钉得住）。
        self._refresh_scene_rect()
        # ★★ v2.6.43：看不全时（want > fit，最小缩放 1.0 下必然如此）
        #   **不能**居中到内容矩形的几何中心 —— 实测 1.0 档下那个点墨迹占比
        #   **0.00%**（几何中心正好落在图的空白区）⇒ 打开软件就是一片空白。
        #   改为居中到**站点分布的中位点**（那里一定有站，画面立刻有内容）。
        if want > fit + 1e-9:
            self.center_on_visible(self._station_centroid() or target.center())
        else:
            self.center_on_visible(target.center())
        self._zoom_target = self._scale
        self._apply_line_width()
        self._apply_station_scale_all()
        self.zoom_changed.emit(self._scale)

    def reset_zoom(self) -> None:
        self.resetTransform()
        self._scale = 1.0
        self._refresh_scene_rect()
        # 居中到「内容 rect」中心，而不是 sceneRect 中心 —— sceneRect 是动态的，
        # 可能因贴合视口而不对称
        base = getattr(self, "_content_rect", None) or self.scene_.sceneRect()
        self.center_on_visible(base.center())
        self._sync_zoom_state()
        self._apply_line_width()
        self._apply_station_scale_all()
        self.zoom_changed.emit(self._scale)

    @staticmethod
    def _nearest_zoom_step_index(scale: float) -> int:
        """离给定内部缩放**最近**的固定档位下标（见 ZOOM_STEPS）。

        ★ v2.7.0：滚轮步进用它把"当前值"归到档位上 —— 这样用户拖过滑块
          （任意值）之后再滚轮，也是从"最近的档"接着往上/下走。
        ★ v2.7.6：档位表由等比改**等差** ⇒ "最近"也跟着改成**算术距离**
          （对数距离是给等比表用的，等差表用它会整体偏向小的一档）。
        """
        s = max(float(scale), 1e-9)
        return min(range(len(ZOOM_STEPS)),
                   key=lambda i: abs(ZOOM_STEPS[i] - s))

    def zoom_to_station(self, station_id: str, target_scale: float = 2.5) -> None:
        # ★★ v2.7.0：`target_scale` 的语义改成**缩放面板显示的数字**（面板最远档
        #   = 1.00×）—— 用户原话：「点击后放大倍率是 21.74 倍，我要求的是 2.5 倍」
        #   （21.74 = 旧的内部 2.5 ÷ 0.115，就是面板显示值）。现在默认 2.5 ⇒
        #   内部变换 = 2.5 × ZOOM_BASE ≈ 0.2875，面板显示正好 **2.5×**。
        inner_scale = float(target_scale) * ZOOM_BASE
        # 夹到合法区间（下限随视口、上限 = 末档 6.00×）—— 2.5× 远在区间内，这里只是保险
        inner_scale = min(max(inner_scale, self._min_scale_for_viewport()),
                          self._zoom_max)
        item = self.station_items.get(station_id)
        if not item:
            return
        # ★ 要定位的站被"单独显示"挡在外面时，先退出单独显示 ——
        #   否则用户搜到一个站，程序把视野飞过去，屏幕上却什么都没有。
        if not self._isolation_allows(station_id):
            self.set_isolated_line("")
        self.resetTransform()
        self.scale(inner_scale, inner_scale)
        self._scale = inner_scale
        # ★ v2.7.0：定位也把目标/累积状态同步过去，否则接着滚轮会从"旧档位"跳
        self._zoom_target = inner_scale
        self._wheel_acc = 0.0
        self._refresh_scene_rect()      # 先补足 sceneRect/滚动范围，再 centerOn
        # ★★ 必须按**圆点坐标**居中，不能用 centerOn(item)（v2.5.4 修）
        #   `centerOn(QGraphicsItem*)` 居中的是 item 的 sceneBoundingRect 中心，
        #   而站点的包围盒 = 圆点 + 旁边的站名 —— 于是居中偏到"圆点+站名"整体
        #   的中心，圆点被挤到左边去。
        #   更糟的是：这里**还没**跑 _apply_station_scale_all()，图元仍是**旧缩放**
        #   的几何 —— 实测此刻标签缩放是 1/0.1055，包围盒宽 445 场景单位，
        #   中心比圆点右偏 **115.66 场景单位**；在 4 倍缩放下就是 **463 屏幕px**，
        #   实测站点落在 x=-26（视口宽 874，正中心应为 437）—— 站点被推出屏幕外。
        #   用户看到的就是"搜到/定位到某站，画面跳过去但那个站不在中间、甚至看不见"。
        # ★ v2.7.16：居中到**可见区**正中（扣掉左右浮层），不然定位过去的站
        #   可能正好被右侧详情面板盖住。
        self.center_on_visible(QPointF(item.pos()))
        self._sync_zoom_state()
        self._apply_line_width()
        self._apply_station_scale_all()
        self.zoom_changed.emit(self._scale)

    # ---------------- v2.6.90：搜索定位闪烁 ----------------
    def blink_station(self, station_id: str, cycles: int = 4,
                      interval_ms: int = 280) -> None:
        """定位到某站后，让它的**圆点光晕 + 站名文字**一起闪几下。

        闪烁 = 定时器翻转 StationDotItem._blink（光晕亮/灭）+
        站名 setOpacity 抖动，不动布局、不触发防重叠重排。
        连续定位（快速搜两个站）时前一个的定时器先停、状态复原。
        """
        item = self.station_items.get(station_id)
        if item is None:
            return
        self._stop_blink()
        self._blink_item = item
        self._blink_state = False
        self._blink_left = cycles * 2 + 1     # 收尾时保证停在"灭"
        t = QTimer(self)
        t.setInterval(interval_ms)
        t.timeout.connect(self._tick_blink)
        self._blink_timer = t
        t.start()

    def _tick_blink(self) -> None:
        it = getattr(self, "_blink_item", None)
        if it is None or it.scene() is not self.scene_:
            self._stop_blink()
            return
        self._blink_state = not self._blink_state
        it.set_blink(self._blink_state)
        # ★ v2.7.14：看图模式下站点图元是藏着的，`set_blink` 触发不了重绘
        #   ⇒ 红环由 drawForeground 画，这里得让视口自己刷一下。
        if getattr(self, "_view_mode", False):
            self.viewport().update()
        self._blink_left -= 1
        if self._blink_left <= 0:
            self._stop_blink()

    def _stop_blink(self) -> None:
        t = getattr(self, "_blink_timer", None)
        if t is not None:
            t.stop()
        it = getattr(self, "_blink_item", None)
        if it is not None and it.scene() is self.scene_:
            it.set_blink(False)      # 透明度必须复原，否则字永久半透明
        self._blink_item = None
        self._blink_timer = None

    def showEvent(self, event):
        super().showEvent(event)
        if not self._first_fit_done:
            self._first_fit_done = True
            self.fit_map()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._zoom_snap is not None:
            self._abort_zoom_snap()   # 视口尺寸变了，快照失效
        if not self._first_fit_done:
            self._first_fit_done = True
            self.fit_map()
            return
        # ★ 视口变大（拉窗口/进全屏）会把缩放下限一起抬高：原本合法的缩放可能
        #   就此跌破下限。不处理的话，"最大化窗口后再滚轮缩放"会重现错位。
        #   _enforce_zoom_floor 内部也会重算 sceneRect（视口变了，余量要跟着变）。
        if self._enforce_zoom_floor():
            self._apply_line_width()
            self._apply_station_scale_all()

    # ==================================================================
    # 选中 / 查询
    # ==================================================================
    def select_station(self, station_id: str, emit: bool = True,
                       reveal: bool = True) -> None:
        """选中某站。

        ★ v2.7.7 新增 `reveal`：
          · `reveal=True`（默认，键盘方向键 / Tab / 搜索定位）⇒ 仍要把该站带进
            可视区（`ensureVisible`）—— 键盘选中的站很可能在屏幕外，不挪就
            "选了个看不见的站"。
          · `reveal=False`（**鼠标单击圆点/站名**）⇒ **画面一动不动**，
            改用"该站闪几下"告诉用户选中了谁（用户原话：「不需要因为点击站点后
            地图跟随挪动，点击站点后对应的站点闪烁即可」）。
        """
        # ★ 同 zoom_to_station：要选中的站在隔离之外时，先恢复显示全部，
        #   否则会出现"选中了一个屏幕上看不见的站"（信息面板有内容、地图上没有）。
        if station_id and not self._isolation_allows(station_id):
            self.set_isolated_line("")
        prev = self._focus_station_id
        for sid, it in self.station_items.items():
            it.set_selected_visual(sid == station_id)
        item = self.station_items.get(station_id)
        if item:
            self._focus_station_id = station_id
            item.setSelected(True)
            if reveal:
                # ★ v2.7.16：可见区 = 扣掉左右浮层那一块。站还在可见区里就别动
                #   画面（键盘连续切换时不该一跳一跳），跑出去了才居中过去。
                p = self.mapFromScene(item.pos())
                vis = self.visible_viewport_rect().adjusted(60, 60, -60, -60)
                if p.isNull() or not vis.contains(p):
                    self.center_on_visible(item.pos())
                else:
                    self.ensureVisible(item, 140, 140)
            else:
                self.blink_station(station_id)
            # 焦点变了 → 站名优先级变了，重排一次（换乘站/焦点站优先显示）
            if prev != station_id:
                self._apply_label_visible(item)
                old = self.station_items.get(prev)
                if old is not None:
                    self._apply_label_visible(old)
            if emit:
                self.station_clicked.emit(station_id)

    def clear_selection(self) -> None:
        """取消所有选中（空白处单击时调用）。"""
        prev = self._focus_station_id
        self._focus_station_id = ""
        for it in self.station_items.values():
            it.set_selected_visual(False)
        self.scene_.clearSelection()
        old = self.station_items.get(prev)
        if old is not None:
            self._apply_label_visible(old)

    def station_at(self, scene_pos: QPointF,
                   for_hover: bool = False) -> Optional[StationDotItem]:
        """鼠标下的站点图元（没有就 None）。

        ★★ v2.7.8 —— 修"电车/云巴劫持悬浮"（用户原话：「很难悬浮选中正常线路，
           像是被电车/云巴劫持了」）。

           病根：`scene_.items()` 是按 **boundingRect 粗筛**的，而站点的
           boundingRect 里装着**站名文字**（一个比圆点大十倍的矩形）。旧代码
           直接取"最上面那个"，于是**谁的字框压住了邻居的圆点，鼠标就归谁**。
           电车/云巴这两条线建得最晚 ⇒ 叠在最上层 ⇒ 最容易抢到别人
           （离屏实测：383 个站里有 41 个站"站在自己圆点上却命中了别人"，
           云巴站「自然博物馆西」一个就抢走 2 个地铁站）。

           现在的规则（跟 v2.6.37 拖站名的 `_label_hit()` 同一套思路）：
             ① **圆点优先** —— 鼠标压在谁的圆点/药丸里就是谁（最贴直觉）；
                两个都压中（同城换乘的圆点挨得近）⇒ 圆心离鼠标最近的那个。
             ② 圆点都没压中 ⇒ 退到**站名框**（复用 `_label_hit()`：框中心最近 +
                一样近看叠放顺序），保证"鼠标放在字上"也还算选中它。
             ③ 都没有 ⇒ None（不再只凭 boundingRect 粗筛就认领）。

           `for_hover=True`（悬浮气泡 / 光标变手型）时**跳过不吃 hover 的图元**：
           @alt 副站体把 `setAcceptHoverEvents(False)` 关掉了，认领它就会出现
           "光标变手型但气泡不出来"的不一致。
        """
        # ★ v2.7.18：看图模式整体走命中表（矢量图元藏了、`_view_scale` 也停在
        #   烘图基准，下面那套 `screen_half()/scale` 的比对会算错 ⇒ 必须绕开）。
        if getattr(self, "_view_mode", False):
            hv = self.view_hit_station(scene_pos)
            if hv is None:
                return None
            if for_hover and not hv.acceptHoverEvents():
                return None
            return hv
        scale = max(self._scale, 1e-6)
        pad = 4.0 / scale                     # 4 屏幕像素的抓取余量
        best, best_d = None, None
        for st in list(self.station_items.values()) + list(self.alt_items.values()):
            if for_hover and not st.acceptHoverEvents():
                continue
            try:
                rx, ry = st.screen_half()
            except Exception:
                continue
            dx = scene_pos.x() - st.pos().x()
            dy = scene_pos.y() - st.pos().y()
            if abs(dx) > rx / scale + pad or abs(dy) > ry / scale + pad:
                continue
            d = dx * dx + dy * dy
            if best_d is None or d < best_d:
                best, best_d = st, d
        if best is not None:
            return best
        # ② 圆点都没压中 ⇒ 看是不是压在谁的站名上
        lab = self._label_hit(scene_pos)
        if lab is not None and not (for_hover and not lab.acceptHoverEvents()):
            return lab
        return None

    def set_add_mode(self, enabled: bool) -> None:
        self.add_mode = enabled
        self.viewport().setCursor(Qt.CrossCursor if enabled
                                  else map_cursor("open"))
        self._cursor_kind = "cross" if enabled else "open"

    # ==================================================================
    # 图例联动
    # ==================================================================
    def _on_line_hover(self, line_id: str, on: bool) -> None:
        """地图上鼠标**悬浮到线路本身**时（v2.6.12）。

        效果与左侧图例悬停同一条线路**完全一致**：那条线加粗、其余变淡
        —— 就是复用 `highlight_line()`。

        ★ 两条守卫：
          ① **正在按着鼠标键时不新增高亮**。拖动站点 / 拖地图时鼠标会一路
             扫过好几条线，不拦住的话画面会跟着一路闪。
             ★ 但 `on=False` 的**恢复**必须照常执行，否则会卡在高亮状态退不出来。
          ② 隔离状态下 `highlight_line()` 自己会让位（见它的注释），这里不用管。
        """
        if on and QApplication.mouseButtons() != Qt.NoButton:
            return
        self.highlight_line(line_id if on else "")

    def highlight_line(self, line_id: str) -> None:
        """高亮某条线路（其它线路变淡）。line_id 为空则全部恢复。

        ★ 处于"单独显示"状态时，这个悬停高亮要**让位**给隔离状态：
          否则鼠标在图例上划过，就会把已经藏掉的线路又变回"半透明的可见线条"。
        """
        if self._isolated_line:
            return
        for lid, it in self.line_items.items():
            if not line_id:
                it.setOpacity(1.0)
                it.screen_width = 4.6
            elif lid == line_id:
                it.setOpacity(1.0)
                it.screen_width = 8.0
            else:
                it.setOpacity(0.18)
                it.screen_width = 4.6
        self._apply_line_width()

    # ------------------------------------------------------------------
    # 单独显示某条线路（双击图例）
    # ------------------------------------------------------------------
    def isolated_line(self) -> str:
        return self._isolated_line

    def _isolation_allows(self, station_id: str) -> bool:
        """这个站点在当前隔离状态下该不该出现。未隔离时恒为 True。"""
        if self._isolated_stations is None:
            return True
        return station_id in self._isolated_stations

    def set_isolated_line(self, line_id: str) -> None:
        """
        只显示某条线路（空串 = 恢复显示全部）。

        会做三件事：
          1. 线路：只留这一条，其余隐藏（注意是隐藏，不是"变淡"——
             用户要的是"只显示"，半透明的别的线仍然会干扰看走向）；
          2. 站点：只留这条线上的站，其余隐藏 + 从站名防重叠排版里剔除；
          3. 通知外界（右下角的车厢编组卡片据此显示/隐藏）。
        """
        line_id = line_id or ""
        if line_id and line_id not in self.line_items:
            line_id = ""                       # 线路不存在就当没隔离
        if line_id == self._isolated_line:
            return                             # 幂等：重复调不重复重排（省一次 O(N²)）
        self._isolated_line = line_id

        if not line_id:
            self._isolated_stations = None
        else:
            dm = get_data_manager()
            seq = set()
            for ln in dm.all_lines():
                if ln.get("id") == line_id:
                    seq = set(x for x in (ln.get("stations") or []) if isinstance(x, str))
                    break
            allow = set()
            for sid, st in dm.all_stations().items():
                # 两个来源都认：站点自己的 lines 字段、以及线路的站点序列。
                # 只认其中一个的话，数据里两边稍有出入就会漏掉站点。
                if line_id in (st.get("lines") or []) or sid in seq:
                    allow.add(sid)
            self._isolated_stations = allow

        # ★ v2.6.32：隔离一换，站名方位锁作废（锁是在"全部线路都显示"下算的）
        self._side_lock = {}
        self._apply_isolation()
        self.isolation_changed.emit(line_id)

    def _apply_isolation(self) -> None:
        """把隔离状态落到图元显隐上，并重排站名。"""
        lid = self._isolated_line

        for l_id, it in self.line_items.items():
            it.setVisible((not lid) or l_id == lid)
            it.setOpacity(1.0)
            it.screen_width = 5.4 if (lid and l_id == lid) else 4.6

        # 焦点站要是被藏了，选中状态一起清掉（否则信息面板还挂着一个看不见的站）
        if lid and self._focus_station_id \
                and not self._isolation_allows(self._focus_station_id):
            self.clear_selection()

        # ★ v2.6.24：线路号方块也是"某条线"的元素，隔离时一起藏
        self._apply_badge_isolation()

        self._restore_station_visibility()
        self._apply_line_width()
        self._invalidate_nn()
        self._update_label_visibility()
        self._snap_dirty = True
        self.viewport().update()

    def register_chrome(self, widget, corner: str = "br") -> None:
        """登记一个"浮在地图之上"的界面控件（见 __init__ 里 _chrome 的说明）。

        corner：锚在哪一角，目前用 "br"（右下）。登记后位置由 `paintEvent`
        统一校正，调用方**不要再自己 move**（自己 move 会拿到滞后的视口尺寸）。
        """
        if widget is None:
            return
        for w, _c in self._chrome:
            if w is widget:
                return
        self._chrome.append((widget, corner or "br"))

    def _raise_chrome(self) -> None:
        for w, _c in self._chrome:
            if w is not None and w.isVisible():
                w.raise_()

    # ------------------------------------------------------------------
    # 浮层控件（chrome）的摆放
    # ------------------------------------------------------------------
    def _layout_chrome(self) -> None:
        """把登记的浮层控件贴到指定角落。

        ★★ 为什么必须在 `paintEvent` 里做，不能靠 `QEvent.Resize` + 手动 move：
            手动 move 读到的 `viewport().width()` 是**上一帧**的值 ——
            实测连续改窗口大小时，卡片位置会一帧一帧地漂：
            1280×800 时 x 从 163 漂到 63，1600×1000 时右边距变成 **-284**（整块跑到
            视口右边界外面去了）。用户在真实窗口上看到的就是"没固定在右下角"。

        ★ 每次绘制前都用**当前**视口尺寸重算，位置永远不可能滞后。
          move 只在坐标真的变了才调，不会引起重绘递归。
        """
        if not self._chrome:
            return
        vp = self.viewport()
        vw, vh = vp.width(), vp.height()
        # ★ v2.6.75："tr" 角支持纵向堆叠 —— 同角第二个控件（图标开关面板）
        #   贴在上一个（缩放面板）正下方 8px，不再互相覆盖。
        tr_next_y: float | None = None
        for w, corner in self._chrome:
            if w is None or not w.isVisible():
                continue
            # 先让它按可用宽度自适应（窄视口下不至于比地图还宽）
            fit = getattr(w, "fit_to_width", None)
            if callable(fit):
                fit(max(120, vw - 2 * CHROME_MARGIN))
            ww, wh = w.width(), w.height()
            # ★ v2.6.43：浮层可用自己的 `chrome_margin` 覆盖全局 16
            #   （用户：「右上方的两个缩放要紧贴右上角边缘」⇒ 面板给 0）
            m = int(getattr(w, "chrome_margin", CHROME_MARGIN))
            if corner == "br":
                x, y = vw - ww - m, vh - wh - m
            elif corner == "bl":
                x, y = m, vh - wh - m
            elif corner == "tr":
                x = vw - ww - m
                if tr_next_y is None:
                    y = m
                else:
                    y = tr_next_y
                tr_next_y = y + wh + 8
            else:
                x, y = m, m
            # 视口比控件还小（极端窄）时退回左上，但绝不越界太多
            x = max(0, min(x, max(0, vw - ww)))
            y = max(0, min(y, max(0, vh - wh)))
            if (w.x(), w.y()) != (x, y):
                w.move(x, y)
            w.raise_()

    def paintEvent(self, event):
        # ★ 浮层位置在每次绘制前校正（见 _layout_chrome 的注释）
        self._layout_chrome()
        super().paintEvent(event)

    def _restore_station_visibility(self) -> None:
        """
        按隔离状态恢复站点图元显隐。

        ★ 缩放收尾（_end_zoom_snap）原来是**无条件 setVisible(True)** ——
          那是为了把动画期间统一藏起来的站点放回来。加了隔离之后不能再无条件：
          否则用户滚一下滚轮，被藏掉的几百个站就全冒出来了。

        ★★ v2.7.15：看图模式下**一律不许放回来** —— 这是堵住"看图模式退化成
          矢量"的总闸门。老缩放链路的收尾必然调到这里，实测放回来后帧耗时
          4.7ms → 31ms（383 个站点 + 站名图元重新参与绘制）。
          退出看图模式由 `exit_view_mode()` 统一恢复（含隔离状态）。
        """
        if getattr(self, "_view_mode", False):
            return
        if not self._isolated_line:
            for it in self.station_items.values():
                it.setVisible(True)
            for it in self.alt_items.values():
                it.setVisible(True)
            for it in self.link_items:
                it.setVisible(True)
            return
        for sid, it in self.station_items.items():
            it.setVisible(self._isolation_allows(sid))
        for aid, it in self.alt_items.items():
            # ★ 副站体跟着它的主站走（id 形如 "湖贝@alt0"）
            it.setVisible(self._isolation_allows(aid.split("@")[0]))
        for it in self.link_items:
            # ★ 两端只要有**一头**还显示，这条虚线就留着 —— 它标的是"这里通向
            #   另一个站体"，把线藏掉反而是丢信息（原图也是这么画的）。
            it.setVisible(any(self._isolation_allows(o) for o in it.owners))

    def fit_to_line(self, line_id: str) -> None:
        """把视图缩放到某条线路的范围。"""
        it = self.line_items.get(line_id)
        if not it:
            return
        rect = it.path().boundingRect()
        if rect.isEmpty():
            return
        rect = rect.adjusted(-320, -320, 320, 320)
        self.fitInView(rect, Qt.KeepAspectRatio)
        self._scale = self.transform().m11()
        self._apply_line_width()
        self._apply_station_scale_all()
        self._sync_zoom_state()
        self.zoom_changed.emit(self._scale)

    def focus_station_by_name(self, name: str) -> bool:
        """按站名（模糊）查找并定位站点，返回是否找到。"""
        name = (name or "").strip()
        if not name:
            return False
        # 精确
        if name in self.station_items:
            self.select_station(name)
            self.zoom_to_station(name)
            return True
        # 模糊
        for sid, it in self.station_items.items():
            if name in sid:
                self.select_station(sid)
                self.zoom_to_station(sid)
                return True
        return False

    # ==================================================================
    # 键盘导航
    # ==================================================================
    def _all_station_items(self) -> List[StationDotItem]:
        """键盘方向键导航用。隔离状态下只在"看得见的站"里找下一个。"""
        return [it for it in self.station_items.values()
                if self._isolation_allows(it.station_id)]

    def _find_nearest_in_direction(self, dx: float, dy: float) -> Optional[StationDotItem]:
        if not self._focus_station_id:
            items = self._all_station_items()
            if not items:
                return None
            vc = self.mapToScene(self.viewport().rect().center())
            return min(items, key=lambda it: (it.pos() - vc).manhattanLength())

        cur = self.station_items.get(self._focus_station_id)
        if cur is None:
            return None

        cp = cur.pos()
        best = None
        best_score = float("inf")
        for it in self._all_station_items():
            if it is cur:
                continue
            p = it.pos()
            vx, vy = p.x() - cp.x(), p.y() - cp.y()
            dot = vx * dx + vy * dy
            if dot <= 0:
                continue
            dist = (vx * vx + vy * vy) ** 0.5
            if dist <= 0:
                continue
            cos_a = dot / dist
            # 距离越近越好 + 方向越正越好（cos^3 让方向权重更高）
            score = dist / max(cos_a ** 3, 0.02)
            if score < best_score:
                best_score = score
                best = it
        return best

    def _move_focus(self, dx: float, dy: float) -> None:
        nxt = self._find_nearest_in_direction(dx, dy)
        if nxt:
            self.select_station(nxt.station_id)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()

        if key in (Qt.Key_Return, Qt.Key_Enter):
            if self._focus_station_id:
                self.station_double_clicked.emit(self._focus_station_id)
            else:
                self.add_station_requested.emit(self.mapToScene(self.viewport().rect().center()))
            event.accept()
            return

        if key == Qt.Key_Left:
            self._move_focus(-1, 0); event.accept(); return
        if key == Qt.Key_Right:
            self._move_focus(1, 0); event.accept(); return
        if key == Qt.Key_Up:
            self._move_focus(0, -1); event.accept(); return
        if key == Qt.Key_Down:
            self._move_focus(0, 1); event.accept(); return

        if key == Qt.Key_Tab:
            items = self._all_station_items()
            if items:
                cur = self.station_items.get(self._focus_station_id)
                if cur is None:
                    self.select_station(items[0].station_id)
                else:
                    items.sort(key=lambda it: (it.pos() - cur.pos()).manhattanLength())
                    if len(items) > 1:
                        self.select_station(items[1].station_id)
            event.accept()
            return

        if key == Qt.Key_Escape:
            # ★ 正在"单独显示某条线路"时，Esc 的**第一职责**是退出单独显示
            #   （这是最常见的"我怎么回到全图"本能动作）；没隔离时才去清选中。
            if self._isolated_line:
                self.set_isolated_line("")
                event.accept()
                return
            self._focus_station_id = ""
            for it in self.station_items.values():
                it.set_selected_visual(False)
            self.scene_.clearSelection()
            event.accept()
            return

        # 键盘 + / - 也能缩放
        if key in (Qt.Key_Plus, Qt.Key_Equal):
            self.wheelEvent(self._fake_wheel(event, 120))
            event.accept(); return
        if key == Qt.Key_Minus:
            self.wheelEvent(self._fake_wheel(event, -120))
            event.accept(); return

        super().keyPressEvent(event)

    def _fake_wheel(self, src_event, delta):
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtCore import QPoint
        pos = self.viewport().rect().center()
        return QWheelEvent(QPointF(pos), self.mapToGlobal(pos),
                           QPoint(0, 0), QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                           Qt.NoScrollPhase, False)

    # ==================================================================
    # 鼠标
    # ==================================================================
    @staticmethod
    def _ev_pos(event) -> QPoint:
        """Qt6 里 QMouseEvent.pos() 已废弃，统一走 position()。"""
        p = event.position() if hasattr(event, "position") else event.pos()
        return p.toPoint() if hasattr(p, "toPoint") else p

    def _scene_at(self, pos: QPoint) -> QPointF:
        """视口坐标 → 场景坐标（**按屏幕上真正看到的映射**）。

        ★★ v2.5.3：手势期间真实变换还停在手势开始时的状态，屏幕上显示的是
        合成帧。此时若直接用 `mapToScene` 做命中测试，点到的是"缩放前/平移前"
        的位置 —— 表现为"拖动之后点站点点不准"。所以手势期间必须用合成帧的
        投影公式反算：  scene = asc + (pos - anchor - pan) / scale
        """
        if self._zoom_snap is not None:
            s = max(self._scale, 1e-6)
            a = self._snap_anchor
            asc = self._snap_anchor_scene
            return QPointF(
                asc.x() + (pos.x() - a.x() - self._snap_pan.x()) / s,
                asc.y() + (pos.y() - a.y() - self._snap_pan.y()) / s,
            )
        return self.mapToScene(pos)

    def set_drag_locks(self, body: bool, label: bool) -> None:
        """★ v2.7.0：两把独立的拖动锁（工具栏 🔒 按钮 + 右键菜单调用）。

          · body=True  —— 锁定轨迹：站点圆点 / 副站体圆点拖不动
                           （metro_render.STATIONS_LOCKED，itemChange 否决）；
          · label=True —— 锁定文字：站名文字拖不动
                           （本类 mouseMoveEvent 里 `_drag_label["locked"]` 跳过）。

        不锁：线路号方块（徽标）、平移缩放、单击选中、编辑弹窗、Ctrl+Z ——
        都不在用户说的影响面里（锁只拦**鼠标拖**，程序化 setPos 照常，
        所以撤销/重做/重载不会把站"锁"在旧位置）。
        """
        from ui import metro_render as _MR
        self.stations_locked = bool(body)
        self.labels_locked = bool(label)
        _MR.set_stations_locked(bool(body))

    def set_stations_locked(self, on: bool) -> None:
        """兼容旧接口（v2.6.89 的单一锁）：等于只改「轨迹」那把，文字不改。"""
        self.set_drag_locks(bool(on), self.labels_locked)

    def _label_hit(self, scene_pos: QPointF) -> Optional[StationDotItem]:
        """鼠标下"站名框盖住这里"的那个站点图元（没有就 None）。

        ★★ v2.6.37 —— 用户：「有些文字比如'下沙'一直都不能被拖动（只能跟随
           站点拖动）」。病根**不在**画错，而在**只问了一个站**：

           老代码 = `item = station_at(pos)`（鼠标下**最上面**那个站点图元）
                    + `item.label_scene_rect().contains(pos)`。
           可站名框常常压在**隔壁站**的圆点/框上（实测：后海←南山书城、
           科苑←高新南、观澜←新澜、龙华←清湖、市民中心←福田…），
           于是拿到的是 B 站，拿 B 的站名框去 contains() 必然 False ⇒
           这个站名**永远**拖不动，只能随站点整块走。

           现在改成：**全站都问一遍**，谁命中就进候选，最后按
            ① 站名框**中心离鼠标最近**（点得离谁的字中间近就是谁 —— 两个
               站名框叠在一起时这条最贴直觉：后海/科苑/观澜就卡在这）；
            ② 一样近时看**叠放顺序**（`scene_.items()` 本来就按上层在前排好，
               画在上面的先给），跟用户眼睛看到的对上。
            ★ 全站扫而不是只扫 `scene_.items()`：后者是按 boundingRect 粗筛，
              站名被外推（ring>0）到框外时捞不着 —— 实测确实有这种站。

        ★ 副站体（`alt_items`，湖贝 5 号线那种第二个站体）**参与**站名命中：
          它们的文字（第二份站名）也要能拖（v2.6.82 用户：「拥有两个同名站点的，
          如红岭南、湖贝，他们的文字都无法被拖动」）。拖的偏移会按 @alt 序号
          写回该站的 alt_bodies[i]（见 main_window._on_label_moved）——
          所以"拖了存不下来"的假象不再成立。副站体的**圆点**仍然不可拖。
        """
        pad = 4.0 / max(self._scale, 1e-6)      # 4 屏幕像素的抓取余量
        zorder = {}
        _n = 0
        for g in self.scene_.items(scene_pos):
            st = g if isinstance(g, StationDotItem) else None
            if st is None:
                p = g.parentItem()
                while p is not None:
                    if isinstance(p, StationDotItem):
                        st = p
                        break
                    p = p.parentItem()
            if st is not None and id(st) not in zorder:
                zorder[id(st)] = _n
                _n += 1
        _far = 1 << 30
        best, best_key = None, None
        # ★ v2.6.82：主站体 + 副站体一起问（谁的字框中心离鼠标最近就是谁；
        #   同近时看叠放顺序）。副站体圆点本身不吃鼠标，这里只借它的**字框**。
        for st in list(self.station_items.values()) + list(self.alt_items.values()):
            if not st.is_label_visible():
                continue
            lr = st.label_scene_rect()
            if not lr.adjusted(-pad, -pad, pad, pad).contains(scene_pos):
                continue
            dx = lr.center().x() - scene_pos.x()
            dy = lr.center().y() - scene_pos.y()
            key = (dx * dx + dy * dy, zorder.get(id(st), _far))
            if best_key is None or key < best_key:
                best, best_key = st, key
        return best

    def mousePressEvent(self, event):
        btn = event.button()
        pos = self._ev_pos(event)
        # ★ 命中测试走"看到的映射"（手势期间 = 合成帧映射），不必为此打断动画
        scene_pos = self._scene_at(pos)
        item = self.station_at(scene_pos)

        # ★★ v2.6.53：**Ctrl + 点站点 = 多选**（最多两个）⇒ 随后右键可编辑
        #   这两站之间的那段线路（水平 / 垂直 / 凸弧 / 凹弧）。
        #   必须排在"拖站名"前面：按着 Ctrl 时用户是要**选站**，不是要拖字。
        if (btn == Qt.LeftButton and item is not None
                and (event.modifiers() & Qt.ControlModifier)):
            self._ctrl_toggle_pick(item.station_id)
            event.accept()
            return
        # 点空白处（没按 Ctrl）⇒ 清掉之前 Ctrl 选的两站（右键时还要用，所以只清左键）
        if (btn == Qt.LeftButton and item is None
                and not (event.modifiers() & Qt.ControlModifier)):
            self.clear_ctrl_picks()

        # ★★ v2.6.32：按在**站名**上 = 单独拖动站名（圆点不动）。
        #   判据用 `label_scene_rect()`（站名在场景里的矩形）稍微放大一点，
        #   让"细长的一条字"也好点中。
        #   ★★ v2.6.37：判定从"只问 station_at() 那一个"改成 `_label_hit()`
        #      （鼠标下所有站点挨个问 + 全站兜底）—— 理由见那里的长注释。
        if (btn == Qt.LeftButton and not self.add_mode
                and os.environ.get("METROEDITOR_NO_LABEL_DRAG", "0") != "1"):
            if self._zoom_snap is not None:
                self._abort_zoom_snap()          # 先落真实变换，坐标才准
                scene_pos = self._scene_at(pos)
            hit_it = self._label_hit(scene_pos)
            if hit_it is not None:
                self._drag_label = {
                    "item": hit_it,
                    "start": QPointF(scene_pos),
                    "off": QPointF(hit_it.label_off()),
                    # ★ v2.6.89：🔒 按下时记下锁状态 —— 拖不动，但松手仍走
                    #   "没拖=单击选中"，点站名选站的手感不变。
                    #   ★ v2.7.0：这里查的是【文字锁】labels_locked（不是轨迹锁）
                    #     —— 右键菜单可以只锁文字或只锁轨迹。
                    "locked": self.labels_locked,
                }
                self._drag_label_moved = False
                self._cursor_kind = "drag"
                self.viewport().setCursor(map_cursor("drag"))
                event.accept()
                return

        # ★★ v2.6.34：按在**线路号方块**上 = 拖这个方块（用户原话
        #   「线路的标志号也改为可以移动位置」）。必须在"空白处拖动平移"
        #   之前判 —— 方块摆在线路外的空地上，不先拦就被当成空白平移了。
        #   ★★ 两个坑（实测踩到的，别删这两行）：
        #     ① 必须 `item is None`（**没按在站点上**）才认徽标 ——
        #        `scene_.items(pos)` 是按 boundingRect 粗筛的，徽标的外框是正方形、
        #        比它画的方块大一圈，站点被徽标外框罩住时，这段会把"拖站点"
        #        整个吃掉（实测点站点中心，站点纹丝不动、撤销栈也不涨）。
        #     ② 还要 `sceneBoundingRect().contains(pos)` —— 光靠 items() 粗筛不够，
        #        同一格里可能有好几个图元。
        if btn == Qt.LeftButton and item is None and not self.add_mode:
            for g in self.scene_.items(scene_pos):
                if not isinstance(g, TerminalBadgeItem) or not g.isVisible():
                    continue
                if not g.sceneBoundingRect().contains(scene_pos):
                    continue
                if self._zoom_snap is not None:
                    self._abort_zoom_snap()
                    scene_pos = self._scene_at(pos)
                self._drag_badge = {"item": g, "start": QPointF(scene_pos),
                                    "off": QPointF(g.badge_off())}
                self._drag_badge_moved = False
                self._cursor_kind = "drag"
                self.viewport().setCursor(map_cursor("drag"))
                event.accept()
                return

        # 添加模式：点空白处 → 新增站点
        if self.add_mode and btn == Qt.LeftButton and item is None:
            if self._zoom_snap is not None:
                self._abort_zoom_snap()
            self.add_station_requested.emit(scene_pos)
            event.accept()
            return

        # ★ 空白处拖动平移：左键点空白 / 中键（任意位置）
        want_pan = (btn == Qt.MiddleButton) or (btn == Qt.LeftButton and item is None)
        if want_pan:
            # ★ v2.7.13：按下时**重算一次**元素边界（用户可能刚拖过站点/站名），
            #   保证这一轮拖动用的是最新边界。只在按下时算，不在 move 里算。
            self._elements_rect(force=True)
            # ★★ v2.5.3：手势期间【不】打断缩放动画 —— 拖动并入同一手势。
            #   以前这里会 `_abort_zoom_snap()`，后果有两个：
            #     ① 立刻落盘 + 同步全场景重绘（150~200ms 冻结）→ 顿挫；
            #     ② 拖动改的是滚动条，而收尾又会按"快照锚点"把滚动条重设一遍，
            #        于是刚拖出来的位移**被覆盖掉** = 拖了白拖、手感像卡住。
            #   现在拖动只累加到 _snap_pan 上，由合成帧实时体现，收尾一并落盘。
            self._panning = True
            self._pan_moved = False
            self._pan_last = QPointF(pos)
            self._last_interact = _perf()
            # v2.6.12：不再用系统的握拳，用"圆环收窄 + 圆心变大"
            self._cursor_kind = "drag"
            self.viewport().setCursor(map_cursor("drag"))
            event.accept()
            return

        # 剩下的是"按在站点上"（要拖动站点 / 交给基类处理）——这时才需要真实变换
        if self._zoom_snap is not None:
            self._abort_zoom_snap()
        # ★ v2.6.81：登记"这次按的是圆点"——松手没拖动就当单击选中。
        #   只在非添加模式记（添加模式点站点不该改选中）；Ctrl/拖站名/拖徽标
        #   的分支早已 return，不会走到这里。
        self._press_dot = item if (btn == Qt.LeftButton and not self.add_mode) else None
        self._press_dot_pos = QPointF(item.pos()) if self._press_dot is not None else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = self._ev_pos(event)

        # ★★ v2.6.34：拖线路号方块（偏移是**场景单位** ⇒ 屏幕上移动多少要先
        #   除以缩放）。跟站名一样：拖动中不重建任何东西，松手才落盘。
        if self._drag_badge is not None:
            db = self._drag_badge
            it = db["item"]
            if it is None or it.scene() is not self.scene_:
                self._drag_badge = None
            else:
                cur = self._scene_at(pos)
                dx = db["off"].x() + (cur.x() - db["start"].x())
                dy = db["off"].y() + (cur.y() - db["start"].y())
                moved_px = (abs(cur.x() - db["start"].x())
                            + abs(cur.y() - db["start"].y())) * max(self._scale, 1e-6)
                if moved_px >= DRAG_THRESHOLD:
                    self._drag_badge_moved = True
                it.set_badge_off(dx, dy)
                self._snap_dirty = True
                event.accept()
                return

        # ★★ v2.6.32：单独拖站名 —— 只改"站名相对圆点的偏移"，圆点不动。
        #   ★ 拖动过程中**不跑全局防重叠排版**（379 站全量 ≈100ms，跟不上鼠标），
        #     松手再排一次；这也符合"我拖到哪就是哪"的直觉。
        if self._drag_label is not None:
            dl = self._drag_label
            it = dl["item"]
            if it is None or it.scene() is not self.scene_:
                self._drag_label = None
            elif dl.get("locked", False):
                # ★ v2.6.89：🔒 锁定中 —— 站名跟手但不动；松手走"没拖=选中"。
                event.accept()
                return
            else:
                cur = self._scene_at(pos)
                s = max(self._scale, 1e-6)
                # ★★ v2.6.40：偏移改成**场景单位**（跟等比站名同一把尺子）。
                #   以前存"屏幕像素"⇒ 缩放时字相对**地图**会跑（缩小时被推远、
                #   放大时贴回圆点压到线上）—— 用户：「修改过位置的站点文字，
                #   缩放的时候会导致错位或者直接不显示」。
                #   鼠标位移换算：**不乘 s**（屏幕上拖多少，字就跟着走多少屏幕像素，
                #   落到场景里自然就是 Δ/s）。
                ddx = cur.x() - dl["start"].x()
                ddy = cur.y() - dl["start"].y()
                dx = dl["off"].x() + ddx
                dy = dl["off"].y() + ddy
                if (abs(ddx) + abs(ddy)) * s >= DRAG_THRESHOLD:
                    self._drag_label_moved = True
                it.set_label_off(dx, dy)
                self._snap_dirty = True
                event.accept()
                return

        if self._panning:
            delta = QPointF(pos) - self._pan_last
            self._pan_last = QPointF(pos)
            if abs(delta.x()) + abs(delta.y()) > 0:
                if (abs(delta.x()) + abs(delta.y())) >= DRAG_THRESHOLD:
                    self._pan_moved = True
                self._last_interact = _perf()
                # ★ v2.7.12：先按"不许拖到全白屏"把这一步的位移夹一遍
                d = self._pan_limit_delta(delta)
                if self._zoom_snap is not None:
                    # ★ 手势期间：平移记在 _snap_pan 上，由合成帧体现
                    self._cancel_reveal()
                    self._snap_pan += d
                    self._snap_dirty = True   # 画面内容变了
                    self._compose_if_due()
                else:
                    h = self.horizontalScrollBar()
                    v = self.verticalScrollBar()
                    h.setValue(h.value() - int(d.x()))
                    v.setValue(v.value() - int(d.y()))
            event.accept()
            return

        super().mouseMoveEvent(event)
        self._sync_cursor(pos)

    def _compose_if_due(self) -> None:
        """拖动引起的重合成：按帧率节流，别让鼠标事件的频率决定耗时。

        ★ 缩放动画在跑时**不额外合成** —— 动画定时器每 10ms 会自己合成一帧，
          这里再插一帧等于白花一倍时间。
        """
        if self._zoom_snap is None or self._zoom_anim.isActive():
            return
        now = _perf()
        if now - getattr(self, "_last_move_compose", 0.0) < 0.013:
            return
        self._last_move_compose = now
        self._update_snap_pixmap()

    def mouseReleaseEvent(self, event):
        btn = event.button()

        # ★★ v2.6.34：线路号方块收尾 —— 真拖过才落盘（单击不写文件）
        if self._drag_badge is not None and btn == Qt.LeftButton:
            db = self._drag_badge
            self._drag_badge = None
            it = db["item"]
            if self._drag_badge_moved and it is not None and it.scene() is self.scene_:
                self._drag_badge_moved = False
                self._persist_badge_offset(it)
                self.badge_moved.emit(it.badge_key)
            self._sync_cursor(self._ev_pos(event), force=True)
            event.accept()
            return

        # ★★ v2.6.32：站名拖动收尾 —— 真拖过才落盘（单击站名不写盘）。
        if self._drag_label is not None and btn == Qt.LeftButton:
            dl = self._drag_label
            self._drag_label = None
            it = dl["item"]
            if self._drag_label_moved and it is not None and it.scene() is self.scene_:
                self._drag_label_moved = False
                self._update_label_visibility()
                self.label_moved.emit(it.station_id)
            else:
                # 没拖动 = 在站名上点了一下 ⇒ 跟点圆点一样：选中该站。
                # ★ v2.6.82：副站体的 id 是「湖贝@alt0」——换算回主站 id 再选。
                # ★ v2.7.7：reveal=False —— 单击不挪动画面（改闪烁提示）。
                self.select_station(it.station_id.split("@alt", 1)[0],
                                    reveal=False)
            self._sync_cursor(self._ev_pos(event), force=True)
            event.accept()
            return

        if self._panning and btn in (Qt.LeftButton, Qt.MiddleButton):
            self._panning = False
            moved = self._pan_moved
            self._pan_moved = False
            if moved:
                # 拖动过了 → 别让随后到来的"双击"误触发新建站点
                self._suppress_dblclick = True
            elif btn == Qt.LeftButton:
                # 空白处单击（没拖动）→ 取消选择
                self.clear_selection()
                # ★ v2.6.90：只认**左键**单击空白（中键拖底图松手不触发）
                self.map_empty_clicked.emit()
            self._sync_cursor(self._ev_pos(event), force=True)
            event.accept()
            return

        # ★ v2.6.81：圆点单击选中 —— 按下时记的是圆点（_press_dot），
        #   松手时圆点没被拖走（位移 < STATION_MOVE_EPS，跟"拖站点落盘"同一判据）
        #   = 用户是"点了一下站点" ⇒ 选中它（弹信息面板 + 固定气泡）。
        #   真拖动过的走 station_moved 落盘，不再额外选中。
        #   ★★ v2.6.88：**确定性收尾** —— 以前指望"图元自己的 mouseReleaseEvent
        #     发 station_moved"，但 view 在这里 accept+return 后事件根本到不了
        #     图元（实测 grabber 卡死、图元挪了数据没同步、撤销无记录）——
        #     是否失效取决于 Qt 事件路由的运气 ⇒ 云巴/有轨电车批量挪站时
        #     "Ctrl+Z 时灵时不灵"。现在在 view 层直接同步数据 + 上报，一次到位。
        if self._press_dot is not None and btn == Qt.LeftButton:
            it, p0 = self._press_dot, self._press_dot_pos
            self._press_dot = None
            self._press_dot_pos = None
            if it is not None and it.scene() is self.scene_ and p0 is not None:
                moved = (abs(it.pos().x() - p0.x()) >= STATION_MOVE_EPS
                         or abs(it.pos().y() - p0.y()) >= STATION_MOVE_EPS)
                if not moved:
                    # 单击选中（副站体换算回主站 id）
                    # ★ v2.7.7：reveal=False —— 单击不挪动画面（改闪烁提示）。
                    self.select_station(it.station_id.split("@alt", 1)[0],
                                        reveal=False)
                elif not getattr(it, "_move_reported", False):
                    # 真拖动：view 层代为收尾（数据同步 + station_moved → 保存/撤销）
                    it._move_reported = True
                    it._snapping = False
                    it.data["x"] = round(it.pos().x(), 1)
                    it.data["y"] = round(it.pos().y(), 1)
                    self.station_moved.emit(it.station_id)
            # ★ release 没送达图元时 Qt 不会自己放 grabber —— 不放掉会毒害下一次
            #   点击/拖动（图元一直攥着鼠标）。明确放掉。
            g = self.scene().mouseGrabberItem()
            if g is not None:
                g.ungrabMouse()
            self._sync_cursor(self._ev_pos(event), force=True)
            event.accept()
            return

        super().mouseReleaseEvent(event)
        self._sync_cursor(self._ev_pos(event), force=True)

    def _sync_cursor(self, view_pos, force: bool = False) -> None:
        """空白处显示"可拖动"光标；站点上显示指向手型。

        ★ v2.6.12：不再用 `cur.shape() != want` 判断要不要换 ——
          自定义位图光标的 `shape()` 一律是 `Qt.BitmapCursor`，
          静止态和拖动态**长得不一样但 shape() 相同**，那条判断会失效
          ⇒ 拖动时光标不会变。改成自己记 `self._cursor_kind`。
        """
        if self._panning:
            kind, cur = "drag", map_cursor("drag")
        elif self.add_mode:
            kind, cur = "cross", Qt.CrossCursor
        else:
            # 节流：光标只挪了几个像素时不重复做场景查询
            if (not force and self._cursor_probe.x() >= 0
                    and abs(view_pos.x() - self._cursor_probe.x()) <= 2
                    and abs(view_pos.y() - self._cursor_probe.y()) <= 2):
                return
            self._cursor_probe = QPoint(int(view_pos.x()), int(view_pos.y()))
            # ★ v2.7.8：跟 hover 气泡同一套命中规则（不然光标和气泡会指向不同的站）
            item = self.station_at(self._scene_at(view_pos), for_hover=True)
            if item is None:
                kind, cur = "open", map_cursor("open")
            else:
                # 站点上保留系统的手指手型：「可点击」是通用语义，别换成圆圈
                kind, cur = "point", Qt.PointingHandCursor
        if force or self._cursor_kind != kind:
            self._cursor_kind = kind
            self.viewport().setCursor(cur)

    def mouseDoubleClickEvent(self, event):
        # ★ v2.7.14：看图模式只能改「详细信息」里的文字 —— 主图上的东西一律
        #   不许动 ⇒ 双击既不弹编辑框、也不新建站点（用户选项④ A）。
        if getattr(self, "_view_mode", False):
            event.accept()
            return
        if self._suppress_dblclick:
            # 上一次是拖动平移，忽略这次"双击"
            self._suppress_dblclick = False
            event.accept()
            return

        scene_pos = self._scene_at(self._ev_pos(event))
        item = self.station_at(scene_pos)

        # ★ v2.6.62：Ctrl + 双击某段线路 ⇒ 同右键，弹"这一段"的菜单
        if item is None and (QApplication.keyboardModifiers() & Qt.ControlModifier):
            try:                       # Qt6：QMouseEvent 只给 globalPosition()
                gpos = event.globalPosition().toPoint()
            except Exception:
                gpos = self.mapToGlobal(self._ev_pos(event))
            if self._seg_menu_at(scene_pos, gpos):
                event.accept()
                return

        if item is None and event.button() == Qt.LeftButton:
            if self._zoom_snap is not None:
                self._abort_zoom_snap()   # 要落真实变换后再新建，坐标才准
            self.add_station_requested.emit(scene_pos)
            event.accept()
            return

        if item and event.button() == Qt.LeftButton:
            if self._zoom_snap is not None:
                self._abort_zoom_snap()
            self.station_double_clicked.emit(item.station_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ---------------- v2.6.53：Ctrl 点两站 ⇒ 右键编辑这两站之间的线路 ----------------
    def _ctrl_toggle_pick(self, sid: str) -> None:
        picks = self._ctrl_picks
        if sid in picks:
            picks.remove(sid)
        else:
            picks.append(sid)
            while len(picks) > 2:        # 只留最后两个：[基准, 被动]
                del picks[0]
        self._apply_pick_visual()

    def _apply_pick_visual(self) -> None:
        picks = set(self._ctrl_picks)
        for sid, it in self.station_items.items():
            it.set_selected_visual(sid in picks or sid == self._focus_station_id)

    def clear_ctrl_picks(self) -> None:
        if not self._ctrl_picks:
            return
        self._ctrl_picks = []
        self._apply_pick_visual()

    @staticmethod
    def _lines_with_adjacent(a: str, b: str):
        """站序里 a、b **正好相邻**的线路 ⇒ [(线号, 前一站, 后一站)]。

        ★ 返回的是**数据里的真实顺序**，不是用户点的顺序：写 segment_shapes 的键
          必须和渲染时 `build_line_points_ex` 用的 key 一致，否则改了不生效。
        """
        try:
            lines = get_data_manager().all_lines()
        except Exception:
            return []
        out = []
        for line in lines:
            seq = line.get("stations") or []
            for i in range(1, len(seq)):
                if (seq[i - 1], seq[i]) == (a, b):
                    out.append((str(line.get("id")), a, b))
                    break
                if (seq[i - 1], seq[i]) == (b, a):
                    out.append((str(line.get("id")), b, a))
                    break
        return out

    @staticmethod
    def _add_shape_actions(menu, cand) -> None:
        lid, p, n = cand
        for text, kind in (("↔ 水平（第二站挪到与第一站齐平）", "h"),
                           ("↕ 垂直（第二站挪到与第一站对齐）", "v"),
                           ("◠ 凸弧（这段线拱起来）", "cup"),
                           ("◡ 凹弧（这段线凹下去）", "cap")):
            act = menu.addAction(text)
            act.setData((lid, p, n, kind))
        # ★ v2.6.55：自动追踪（甲）—— 这一段照官方原图描出来
        menu.addSeparator()
        act = menu.addAction("🧭 按官方原图描这一段（自动追踪）")
        act.setData(("trace", lid, p, n))

    def _apply_segment_shape(self, lid, prev, nxt, kind, anchor, mover) -> None:
        dm = get_data_manager()
        if kind in ("h", "v"):
            # ★ 用户定的规则：**第一个站不动，第二个站挪过去**
            sa = dm.all_stations().get(anchor) or {}
            sb = dm.all_stations().get(mover)
            if not sa or sb is None:
                return
            if kind == "h":
                sb["y"] = float(sa.get("y", sb.get("y", 0.0)))
            else:
                sb["x"] = float(sa.get("x", sb.get("x", 0.0)))
        else:
            seg = dm.lines_doc.get("segment_shapes")
            if not isinstance(seg, dict):
                seg = {}
                dm.lines_doc["segment_shapes"] = seg
            seg["%s|%s|%s" % (lid, prev, nxt)] = kind
        self._commit_data()

    def _commit_data(self) -> None:
        """改了业务数据后的统一收口：压快照 + 落盘 + 重画线路。"""
        w = self.window()
        if hasattr(w, "_save_data"):
            w._save_data()          # ★ 内部先把上一次快照压栈 ⇒ Ctrl+Z 回得来
        else:
            get_data_manager().save()
        self.rebuild_lines()
        self._apply_pick_visual()

    # ------------------------------------------------------------------
    # ★ v2.6.55 自动追踪：让线条照着官方原图走（甲）+ 站点吸到走廊（乙）
    # ------------------------------------------------------------------
    def _auto_trace_seg(self, lid: str, a: str, b: str) -> bool:
        """照**官方原图**描出这一段，写进 `lines_doc["traced"]`。

        ★ 写 lines_doc 而不是独立 json ⇒ 落盘 + Ctrl+Z 撤销自动就有。
        ★ 端点用**渲染时真正用的那个点**（`line_station_xy`，含 alt_bodies 的
          同名站拆分），不然描出来的路径跟画出来的线错开一截。
        """
        from ui import trace_assist as TA
        if not TA.available():
            return False
        dm = get_data_manager()
        st = dm.all_stations()
        sa, sb = st.get(a), st.get(b)
        if not sa or not sb:
            return False
        ax, ay = line_station_xy(sa, lid)
        bx, by = line_station_xy(sb, lid)
        pts = TA.trace(lid, ax, ay, bx, by)
        if not pts:
            return False
        d = dm.lines_doc.get("traced")
        if not isinstance(d, dict):
            d = {}
            dm.lines_doc["traced"] = d
        d["%s|%s|%s" % (lid, a, b)] = [[round(float(p[0]), 1), round(float(p[1]), 1)]
                                        for p in pts]
        return True

    def auto_trace_all(self) -> Tuple[int, int, List[str]]:
        """全图自动描线（甲）。返回 (成功段数, 总段数, 描不出来的段列表)。

        ★ 一次压一份快照 ⇒ Ctrl+Z 一下就能整体撤回，不用怕"描坏了回不去"。
        ★ 描不出来的段**保持原来的画法**（不做任何猜测），名单交给用户 ——
          信任红线：自动化测的东西必须由用户过目，不能偷偷改。
        """
        from ui import trace_assist as TA
        if not TA.available():
            return (0, 0, ["点云 data/trace_cloud.json 不存在"])
        dm = get_data_manager()
        st = dm.all_stations()
        ok = tot = 0
        failed: List[str] = []
        for L in (dm.lines_doc.get("lines") or []):
            lid = str(L.get("id"))
            seq = [n for n in (L.get("stations") or []) if n in st]
            for i in range(1, len(seq)):
                tot += 1
                if self._auto_trace_seg(lid, seq[i - 1], seq[i]):
                    ok += 1
                else:
                    failed.append("%s号线 %s→%s" % (lid, seq[i - 1], seq[i]))
        if ok:
            self._commit_data()
        return (ok, tot, failed)

    def clear_auto_trace(self) -> int:
        """清掉全部自动描线（退回原来的八向画法）。返回清掉了几段。"""
        dm = get_data_manager()
        d = dm.lines_doc.get("traced")
        n = len(d) if isinstance(d, dict) else 0
        if n:
            dm.lines_doc["traced"] = {}
            self._commit_data()
        return n

    def deviation_rows(self, min_dev: float = 25.0, limit: int = 60
                       ) -> List[Tuple[str, str, float]]:
        """偏差提示：哪些站**离官方走廊**比较远。

        返回 [(站名, 线号, 偏差像素)]，按偏差从大到小。
        ★ 这是"我还是无法让线条跟随底图"的**体检报告** —— 名单上的站就是
          需要手动拖一下（开了吸附会自己啪一下归位）的那些。
        """
        from ui import trace_assist as TA
        if not TA.available():
            return []
        dm = get_data_manager()
        st = dm.all_stations()
        rows: List[Tuple[str, str, float]] = []
        for L in (dm.lines_doc.get("lines") or []):
            lid = str(L.get("id"))
            for n in (L.get("stations") or []):
                s = st.get(n)
                if not s:
                    continue
                x, y = line_station_xy(s, lid)
                dv = TA.deviation(lid, x, y)
                if dv is not None and dv >= min_dev:
                    rows.append((n, lid, dv))
        rows.sort(key=lambda r: -r[2])
        return rows[:limit]

    def _segment_menu(self, anchor: str, mover: str, gpos) -> None:
        """两站之间那段线路的编辑菜单（anchor = 先点的那个，不动）。"""
        def nm(sid):
            st = get_data_manager().all_stations().get(sid) or {}
            return st.get("station_name") or sid

        cands = self._lines_with_adjacent(anchor, mover)
        if not cands:
            QMessageBox.information(
                self, "不是相邻站",
                f"「{nm(anchor)}」和「{nm(mover)}」在任何一条线上都不是**相邻**两站，\n"
                "这两站之间没有单独的一段线路可以编辑。")
            return
        menu = QMenu(self)
        head = menu.addAction(f"📐 {nm(anchor)} ↔ {nm(mover)} 之间的线路")
        head.setEnabled(False)
        menu.addSeparator()
        if len(cands) == 1:
            self._add_shape_actions(menu, cands[0])
        else:                       # 两站同属多条线 ⇒ 让用户挑是哪条线
            for cand in cands:
                self._add_shape_actions(menu.addMenu(f"{cand[0]} 号线"), cand)
        chosen = menu.exec(gpos)
        if chosen is None:
            return
        d = chosen.data()
        if isinstance(d, tuple) and len(d) == 4:
            if d[0] == "trace":                    # ★ 自动描线（甲）
                done = self._auto_trace_seg(d[1], d[2], d[3])
                w = self.window()
                if hasattr(w, "_toast"):
                    w._toast("已按原图描这一段 ✅" if done else
                             "这段描不出来（原图上被别的线/站牌盖住了）",
                             "#22C55E" if done else "#EF4444")
                if done:
                    self._commit_data()
                return
            self._apply_segment_shape(d[0], d[1], d[2], d[3], anchor, mover)

    # --------- v2.6.62：Ctrl + 光标停在某段线路上 ⇒ 双击/右键弹"这一段"菜单 ---------
    SEG_HIT_PX = 30.0     # 屏幕上多少像素以内算"点在这条线上"

    def _toast(self, msg: str, color: str = "#22C55E") -> None:
        w = self.window()
        if hasattr(w, "_toast"):
            w._toast(msg, color)

    @staticmethod
    def _dist_polyline(px: float, py: float, pl: List) -> float:
        """点到折线的最短距离（场景单位）。"""
        best = 1e18
        for i in range(len(pl) - 1):
            x0, y0 = float(pl[i][0]), float(pl[i][1])
            x1, y1 = float(pl[i + 1][0]), float(pl[i + 1][1])
            dx, dy = x1 - x0, y1 - y0
            L2 = dx * dx + dy * dy
            if L2 < 1e-9:
                t = 0.0
            else:
                t = ((px - x0) * dx + (py - y0) * dy) / L2
                t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            ex = x0 + dx * t - px
            ey = y0 + dy * t - py
            d2 = ex * ex + ey * ey
            if d2 < best:
                best = d2
        return math.sqrt(best) if best < 1e17 else 1e18

    def _seg_at(self, scene_pos: QPointF, max_screen_px: float = SEG_HIT_PX):
        """鼠标下"两站之间"的那一段 ⇒ (线号, 前站, 后站)；没点到就 None。

        ★ 距离是对**真正画出来的那条折线**量的（这段有描线点就用描线点），
          不是对 A→B 直线量 —— 官方是 L 形的地方，点在直线边上会判"没点到"。
        ★ 只看站序里**真正相邻**的两站 ⇒ 拿到的 key 和 `traced` 的键一致
          （渲染时也是这个键，改了才生效）。
        """
        dm = get_data_manager()
        st = dm.all_stations()
        traced = dm.lines_doc.get("traced") or {}
        px, py = scene_pos.x(), scene_pos.y()
        best = None
        for L in (dm.lines_doc.get("lines") or []):
            lid = str(L.get("id"))
            seq = [n for n in (L.get("stations") or []) if n in st]
            for i in range(1, len(seq)):
                a, b = seq[i - 1], seq[i]
                ax, ay = line_station_xy(st[a], lid)
                bx, by = line_station_xy(st[b], lid)
                pl = [(ax, ay), (bx, by)]
                tp = traced.get("%s|%s|%s" % (lid, a, b))
                if isinstance(tp, (list, tuple)):
                    mid = [(float(p[0]), float(p[1])) for p in tp
                           if isinstance(p, (list, tuple)) and len(p) >= 2]
                    if len(mid) >= 2:
                        pl = [(ax, ay)] + mid + [(bx, by)]
                d = self._dist_polyline(px, py, pl)
                if best is None or d < best[0]:
                    best = (d, lid, a, b)
        if best is None:
            return None
        if best[0] > max_screen_px / max(self._scale, 1e-6):
            return None
        return (best[1], best[2], best[3])

    @staticmethod
    def _fmt_dev(v) -> str:
        return "—" if v is None else "%.1f px" % v

    def _seg_menu_at(self, scene_pos: QPointF, gpos) -> bool:
        """Ctrl + 光标停在某段线路上 ⇒ 弹"这一段怎么走"的菜单。返回有没有弹。

        ★ 菜单**先给数字再让你点**：每种画法离官方中心线多远（p90）直接写在
          菜单项上，官方明明是弯的段你偏要拉直时会标 ⚠️ ⇒ 不用盲选，
          也不用跑"偏差检查"才知道结果。
        """
        seg = self._seg_at(scene_pos)
        if seg is None:
            return False
        lid, a, b = seg
        dm = get_data_manager()
        st = dm.all_stations()
        sa, sb = st.get(a), st.get(b)
        if not sa or not sb:
            return False
        ax, ay = line_station_xy(sa, lid)
        bx, by = line_station_xy(sb, lid)
        cur = (dm.lines_doc.get("traced") or {}).get("%s|%s|%s" % (lid, a, b))
        rep = None
        try:
            from ui import trace_assist as TA
            if TA.available():
                rep = TA.seg_report(lid, ax, ay, bx, by, cur)
        except Exception:
            rep = None

        def nm(sid):
            s = st.get(sid) or {}
            return s.get("station_name") or sid

        menu = QMenu(self)
        head = menu.addAction("📐 %s号线 %s ↔ %s" % (lid, nm(a), nm(b)))
        head.setEnabled(False)
        dev_now = (rep or {}).get("dev_now")
        if dev_now is not None:
            s = menu.addAction("　现在离底图 %s（p90，越小越贴）" % self._fmt_dev(dev_now))
            s.setEnabled(False)
        menu.addSeparator()

        dl = (rep or {}).get("dev_line")
        da = (rep or {}).get("dev_arc")
        adv = (rep or {}).get("advice") or "keep"
        t_line = "📏 转为直线　→ %s" % self._fmt_dev(dl)
        if dl is not None and dev_now is not None and dl > dev_now + 3.0:
            t_line += "　⚠️ 会脱线"        # 官方这段本来是弯的，拉直会离开底图
        if adv == "line":
            t_line += "　✅ 建议"
        t_arc = "🌙 探测弧度　→ %s" % self._fmt_dev(da)
        if adv == "arc":
            t_arc += "　✅ 建议"
        act_line = menu.addAction(t_line)
        act_arc = menu.addAction(t_arc)
        menu.addSeparator()
        act_trace = menu.addAction("🧭 按官方原图描这一段（逐点照抄）")
        act_clear = menu.addAction("↩️ 清除这一段的自定义走法")
        if not isinstance(cur, list):
            act_clear.setEnabled(False)

        chosen = menu.exec(gpos)
        if chosen is None:
            return True
        if chosen == act_line:
            self._apply_seg_straight(lid, a, b)
        elif chosen == act_arc:
            self._apply_seg_arc(lid, a, b, rep)
        elif chosen == act_trace:
            done = self._auto_trace_seg(lid, a, b)
            self._toast("已按原图描这一段 ✅" if done else
                        "这段描不出来（原图上被别的线/站牌盖住了）",
                        "#22C55E" if done else "#EF4444")
            if done:
                self._commit_data()
        elif chosen == act_clear:
            self._clear_seg(lid, a, b)
        return True

    def _apply_seg_straight(self, lid: str, a: str, b: str) -> None:
        """「转为直线」：删掉这一段的描线点和弧形状 ⇒ 回到 A→B 直连（八向）。"""
        dm = get_data_manager()
        key = "%s|%s|%s" % (lid, a, b)
        n = 0
        for field in ("traced", "segment_shapes"):
            d = dm.lines_doc.get(field)
            if isinstance(d, dict) and key in d:
                del d[key]
                n += 1
        if not n:
            self._toast("这一段本来就是直连", "#64748B")
            return
        self._commit_data()
        self._toast("已转为直线 ✅（不对就 Ctrl+Z）", "#22C55E")

    def _apply_seg_arc(self, lid: str, a: str, b: str, rep=None) -> None:
        """「探测弧度」：沿官方中心线拟合一条平滑的弧，写进 `traced`。

        ★ 自检：贴底图的程度**变差超过 3px 就不采用**（宁可不动，也不能画离谱）
          —— 信任红线：自动化改的东西必须经得起"离官方多远"这一把尺子。
        """
        from ui import trace_assist as TA
        dm = get_data_manager()
        st = dm.all_stations()
        sa, sb = st.get(a), st.get(b)
        if not sa or not sb:
            return
        ax, ay = line_station_xy(sa, lid)
        bx, by = line_station_xy(sb, lid)
        pts = (rep or {}).get("arc_pts") or TA.trace_smooth(lid, ax, ay, bx, by)
        if not pts:
            self._toast("这段探测不出来（原图上被别的线/站牌盖住了）", "#EF4444")
            return

        def dev_of(mid):
            """量"离底图多远"：**必须带上两端站点**（traced 只存中间点）。"""
            return TA.cloud_dev(lid, [(ax, ay)] + [tuple(p[:2]) for p in mid]
                                + [(bx, by)])

        new_dev = dev_of(pts)
        old_dev = (rep or {}).get("dev_now")
        if old_dev is None:
            # ★ rep 没给（点云没加载 / 体检出错）时**自己量一份**，不能因此跳过自检
            cur = (dm.lines_doc.get("traced") or {}).get("%s|%s|%s" % (lid, a, b))
            old_dev = dev_of(cur if isinstance(cur, list) else [])
        if new_dev is not None and old_dev is not None and new_dev > old_dev + 3.0:
            self._toast("探测结果反而更差（%.1f → %.1f px），已放弃"
                        % (old_dev, new_dev), "#EF4444")
            return
        d = dm.lines_doc.get("traced")
        if not isinstance(d, dict):
            d = {}
            dm.lines_doc["traced"] = d
        d["%s|%s|%s" % (lid, a, b)] = [[round(float(p[0]), 1), round(float(p[1]), 1)]
                                        for p in pts]
        self._commit_data()
        self._toast("已探测弧度 → %s ✅（不对就 Ctrl+Z）" % self._fmt_dev(new_dev),
                    "#22C55E")

    def _clear_seg(self, lid: str, a: str, b: str) -> None:
        dm = get_data_manager()
        d = dm.lines_doc.get("traced")
        key = "%s|%s|%s" % (lid, a, b)
        if isinstance(d, dict) and key in d:
            del d[key]
            self._commit_data()
            self._toast("已清除这一段的自定义走法 ✅", "#22C55E")

    def contextMenuEvent(self, event):
        scene_pos = self._scene_at(event.pos())
        item = self.station_at(scene_pos)
        # ★ v2.6.62：Ctrl + 光标停在某段线路上 ⇒ 直接弹"这一段"的菜单
        #   （不用先点两站；"Ctrl 点两站再右键"的老办法保留，选了两站时优先用它）
        if item is None and (QApplication.keyboardModifiers() & Qt.ControlModifier):
            if self._seg_menu_at(scene_pos, event.globalPos()):
                event.accept()
                return
        # ★ v2.6.53：Ctrl 选好了两站 ⇒ 优先弹"这两站之间这段线"的编辑菜单
        if len(self._ctrl_picks) == 2:
            self._segment_menu(self._ctrl_picks[0], self._ctrl_picks[1],
                               event.globalPos())
            return
        if not item:
            # ★ v2.7.1：空白处右键 ⇒ 交给主窗口弹"界面编排"菜单（四类）。
            #   是否真的弹由主窗口决定（编辑模式下它自己会跳过）。
            self.blank_context_requested.emit(event.globalPos())
            event.accept()
            return

        menu = QMenu(self)
        act_edit = menu.addAction("✏️ 编辑该站点")
        act_zoom = menu.addAction("🔍 放大查看")
        act_copy = menu.addAction("📋 复制站点 ID")
        act_del = menu.addAction("🗑️ 删除该站点")
        chosen = menu.exec(event.globalPos())

        if chosen == act_edit:
            self.station_double_clicked.emit(item.station_id)
        elif chosen == act_zoom:
            self.zoom_to_station(item.station_id)
        elif chosen == act_copy:
            QApplication.clipboard().setText(item.station_id)
            QMessageBox.information(self, "已复制", f"station_id: {item.station_id}")
        elif chosen == act_del:
            r = QMessageBox.question(
                self, "确认删除",
                f"删除站点「{item.data.get('station_name')}」？此操作只删除软件内记录。",
                QMessageBox.Yes | QMessageBox.No,
            )
            if r == QMessageBox.Yes:
                dm = get_data_manager()
                dm.delete_station(item.station_id)
                dm.save()
                self.remove_station(item.station_id)
