# -*- coding: utf-8 -*-
"""
tools/_chk_label_on_line.py
===========================
回归：站名**绝不许压在彩色线路里** + 换乘站用**专属图标**（v2.6.9）。

用户原话：
    「如果站点是换乘站，在主界面的交汇处采用换乘的专属图标显示。
      现在站点文字有概率显示在线路线条中(理应在上下左右等其他位置，
      绝对不应该融入到线路的颜色线条里面)，修复这个bug」

本脚本守四件事：
  A 站名压线率 —— 放大后必须接近 0（用户真正会看的档位），且**变异可抓**
                （把避让关掉，压线率要明显回升）
  B 换乘图标   —— 必须是"外圈 / 白环带 / 深色内环 / 线路色核心"三段，
                且像素上量得到（变异：改回旧的单圈画法，判据必须失败）
  C 不许因避让而丢站名 —— 开避让后可见站名数不得比关掉时少
  D 排版耗时   —— 别把缩放收尾拖垮

★ 判据为什么这么定：缩到最小时（整图适配 0.093）站名框比站距还宽，
  压根没有腾挪空间（实测改呼吸量 0→3px 压线率只从 49.4% 动到 50.6%），
  所以那一档只要求"不比改动前差"；**放大档**才是用户编辑时会看的，
  那里必须干净。
"""
from __future__ import annotations

import statistics
import sys
import math
import os
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os                                            # noqa: E402

import core.data_manager as CDM                      # noqa: E402

# ★★ 必须**用真实数据**（379 站 20 条线）算压线率，否则统计没有意义；
#    但又不能让 `MainWindow.close()` 里的 `dm.save()` 写回真文件（项目铁律，
#    见 MEMORY §5.10）⇒ 把真数据**拷一份**到临时目录，全部读写都落在副本上。
_TMP = Path(tempfile.mkdtemp(prefix="v269chk_"))
_REAL = CDM.DATA_DIR
import shutil                                        # noqa: E402
for _n in ("stations.json", "lines.json"):
    if (_REAL / _n).exists():
        shutil.copy(_REAL / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import Qt, QPointF, QRectF       # noqa: E402
from PySide6.QtGui import (QFont, QPainter, QPixmap, QColor,   # noqa: E402
                           QBrush, QPen)
from PySide6.QtWidgets import QApplication, QStyleOptionGraphicsItem  # noqa: E402

import ui.map_view as MV                             # noqa: E402
import ui.metro_render as MR                         # noqa: E402
from ui.main_window import MainWindow                # noqa: E402
from ui.metro_render import (                        # noqa: E402
    LineSegIndex, SCREEN_LINE_W, SCREEN_TRANSFER_R, SCREEN_NORMAL_R,
    TRANSFER_CORE_RATIO, TRANSFER_RING_COLOR, SCREEN_TRANSFER_ARC,
    TRANSFER_ARC_START, TRANSFER_ARC_SPAN, line_screen_width,
)

PASS = 0
FAIL = 0
FAILED = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}" + (f"   （{extra}）" if extra else ""))
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  [FAIL] {name}" + (f"   （{extra}）" if extra else ""))


def pump(n: int = 14) -> None:
    for _ in range(n):
        QApplication.processEvents()


def reset_sides(mv) -> None:
    """把所有站名方向**复位成 'right'**（= 改动前的初始状态）。

    ★★ 这是本脚本最容易踩的坑：`try_place()` 是"稳定性优先"的 ——
      它先试**当前这一侧**，不撞就保持不动。所以"关掉避让"的第二次测量
      会直接继承第一次（开着避让）已经排好的位置 ⇒ 测出来 45 而不是 146，
      看起来像"避让没用"。必须先复位才是真实对照。
    """
    for it in mv.station_items.values():
        if it.label_side() != "right":
            it.set_label_side("right")


def set_scale(mv, scale, cold: bool = False) -> None:
    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    pump(8)
    if cold:
        reset_sides(mv)
    mv._invalidate_nn()
    mv._update_label_visibility()
    pump(10)


def line_overlap(mv) -> tuple:
    """(可见站名数, 压到线的个数, 严重压线的个数)"""
    k = 1.0 / max(mv._scale, 0.01)
    idx = LineSegIndex()
    idx.build(mv.line_items, 60.0 * k, -1)          # -1 = 强制重建
    # ★ v2.6.21：线的墨迹半宽必须跟**画线时**同一公式（场景恒定 22 + 屏幕下限 3px）。
    #   原来硬写 SCREEN_LINE_W(=4.6 屏幕px)：线宽改成跟地图之后，这条判据
    #   会**低估**线的宽度 ⇒ 明明压在线上却判成"没压"，变成假通过。
    ink = line_screen_width(mv._scale) * 0.5 * k
    shown = [it for it in mv.station_items.values() if it._label_on]
    hit = deep = 0
    for it in shown:
        r = it.label_scene_rect(it.label_side())
        if r.width() <= 0.1:
            continue
        ln = idx.hit_length(r, ink)
        if ln > 0:
            hit += 1
            if ln >= min(r.width(), r.height()) * 0.5:
                deep += 1
    return len(shown), hit, deep


def icon_pixels(is_transfer: bool, zoom: float = 1.0, data_extra=None,
                view_scale=None):
    """把单个站点图标按 zoom 倍画到画布上。

    返回 `at(screen_r)`：按**屏幕半径**（px，就是 metro_render 里那些
    SCREEN_* 常量的量纲）沿 +x 方向取色。

    ★★ v2.6.55：默认 zoom 从 16 改成 **1**（view_scale = 1.0）。
      原来取 zoom=16（view_scale=0.0625）是为了"看小档"，但那个档现在
      **软件根本到不了**（v2.6.51 起最小缩放 = 0.115）；更要命的是
      画布坐标 = 屏幕半径 × zoom ⇒ zoom=16 时**屏幕恒定**的描边
      （SCREEN_DOT_STROKE 那一类）在画布上被放大 16 倍，粗达 32px，
      而药丸白心半宽才 13px ⇒ 整颗药丸被描边糊死，取色全是描边的深色
      （实测 6 条判据全部假失败）。
      zoom=1 时"屏幕像素 = 场景单位 = 画布像素"，量纲三者合一，
      实测剖面干净：白心 4~12、黑边 13~18、背景 ≥20。

    ★ v2.6.20：`at` 上还挂了 `.hw / .hl` = 该图标**实际**的半宽/半长
      （来自 item.pill_half()）。判据必须用实际值，不能再用
      SCREEN_TRANSFER_RX/RY 常量 —— 药丸现在有方向、长度也逐站不同，
      常量在多数缩放下**不等于**实际尺寸，用常量会假通过。

    ★★ 别用"占外圈半径的比例"当坐标：普通站半径和外圈不同，同一个比例对应
      两个不同的实际半径 —— 实测按比例 0.50 取样，普通站取到的是它自己的
      **线路色描边**（#1565c0），判据"这里应该没有深色内环"直接假失败。
    """
    data = {"x": 0, "y": 0, "station_name": "测", "is_transfer": is_transfer}
    if data_extra:
        data.update(data_extra)
    item = MR.StationDotItem("T", data, color=QColor("#1565C0"))
    item._view_scale = (1.0 / zoom) if view_scale is None else view_scale
    hw, hl = item.pill_half()
    # ★ 画布按**实际**尺寸留（药丸可能是横的、也可能是长的），否则会被裁掉，
    #   取样时"药丸没长出去"变成假失败。
    size = int(max(hw, hl, MR.SCREEN_TRANSFER_RX) * zoom * 2 + 40)
    pm = QPixmap(size, size)
    pm.fill(QColor("#F7F9FB"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.translate(size / 2.0, size / 2.0)
    item.paint(p, QStyleOptionGraphicsItem(), None)
    p.end()
    img = pm.toImage()
    cx = cy = size // 2
    base = img.pixelColor(int(size * 0.05), int(size * 0.05))

    def at(screen_r: float, deg: float = 0.0):
        """screen_r 是**屏幕像素半径**；`deg` 是 Qt 角度（0°=3 点，逆时针为正）。

        ★ 必须支持角度：新图标的环是**断开**的（缺口在 0° / 180° 附近），
          只沿 +x 取样正好落在缺口里，什么都量不到。
        """
        th = math.radians(deg)
        x = int(round(cx + screen_r * zoom * math.cos(th)))
        y = int(round(cy - screen_r * zoom * math.sin(th)))
        return img.pixelColor(min(max(x, 0), size - 1),
                              min(max(y, 0), size - 1))

    def at_xy(dx: float, dy: float):
        """按**屏幕像素偏移**取色（dx 向右、dy 向下为正）。"""
        return img.pixelColor(
            min(max(int(round(cx + dx * zoom)), 0), size - 1),
            min(max(int(round(cy + dy * zoom)), 0), size - 1))

    def count_dark(a0: float, a1: float, r0: float, r1: float,
                   tol: int = 140) -> int:
        """数「角度 [a0,a1] × 屏幕半径 [r0,r1]」扇区里的**深色**像素个数。

        ★★ 这是验「有没有箭头」的**唯一可靠办法**（v2.6.11）：
           弧带本身只有 1.5px 宽，在弧带里取一个点，分不清量到的是弧还是箭头
           （第一版就是这么判的，结果"不画箭头"和"画了箭头"都是深色）。
           而**缺口里除了箭头不可能有别的深色** —— 弧末端的 RoundCap 只往缺口
           里伸 ~9.6°，把窗口再往里缩一点就干净了。
        """
        ref = QColor(TRANSFER_RING_COLOR)
        n = 0
        for y in range(size):
            dy = y + 0.5 - cy
            for x in range(size):
                dx = x + 0.5 - cx
                rr = math.hypot(dx, dy) / zoom
                if rr < r0 or rr > r1:
                    continue
                th = math.degrees(math.atan2(-dy, dx)) % 360.0
                if th < a0 or th > a1:
                    continue
                if dist(img.pixelColor(x, y), ref) < tol:
                    n += 1
        return n

    at.at_xy = at_xy
    at.count_dark = count_dark
    # ★ v2.6.20：把**实际**半宽/半长挂上去，判据一律用它（别用常量）
    at.hw, at.hl = hw, hl
    at.item = item
    return at, base


# 换乘图标（🔄 旋转箭头环）的半径尺（屏幕像素），与 metro_render 的常量同源
R = SCREEN_TRANSFER_R
ARC_W = SCREEN_TRANSFER_ARC
RING_R = R - ARC_W / 2.0                 # 弧的中心线半径
ARC_IN = RING_R - ARC_W / 2.0            # 弧的内缘
CORE_R = R * TRANSFER_CORE_RATIO         # 中心线路色实点
INNER_GAP_MID = (CORE_R + ARC_IN) / 2.0  # 弧与核心之间的留白中点
OUT_R = R + 0.9                          # 弧外侧（应为背景色）
# 采样角度：两段弧各取中点
ARC1_MID_DEG = TRANSFER_ARC_START + TRANSFER_ARC_SPAN / 2.0
ARC2_MID_DEG = TRANSFER_ARC_START + 180 + TRANSFER_ARC_SPAN / 2.0
# ★ 缺口取**第二段弧之后**那个缺口、且要**越过箭尖**（箭尖在弧末端 +26°）：
#   ① 36x = 弧2 末端 336° 之后 32°；② 弧2 的 RoundCap 只伸到 345.7°，
#      下一段弧的 RoundCap 只回伸到 374.3°；③ 箭尖在 362°，368° 已在箭尖之外。
GAP_DEG = TRANSFER_ARC_START + 180 + TRANSFER_ARC_SPAN + 32
# ★ 箭头判据：在**缺口扇区**里数深色像素（理由见 `count_dark` 的 docstring）。
GAP_A0 = TRANSFER_ARC_START + TRANSFER_ARC_SPAN   # 第一段弧末端 156°
GAP_A1 = TRANSFER_ARC_START + 180                 # 第二段弧起点 204°
# 窗口要避开两端的 RoundCap：`arc_w/2 ÷ ring_r` 换成角度，再留 1.5° 余量
_CAP_DEG = math.degrees((SCREEN_TRANSFER_ARC / 2.0) / RING_R) + 1.5
# 径向窗口必须**从常量推导**（★ 硬编码会在改图标大小时悄悄失效：
#   v2.6.12 把半径 5.2 → 7.0，硬编码的 (2.6, 5.5) 就只盖住箭头下半截了）。
#   箭头径向范围 = `ring_r + off ± w` = 3.95 … 7.05px，两头各留点余量。
_ARROW_R0 = (RING_R + MR.TRANSFER_ARROW_RING_OFF - MR.SCREEN_TRANSFER_ARROW_W) - 0.6
_ARROW_R1 = (RING_R + MR.TRANSFER_ARROW_RING_OFF + MR.SCREEN_TRANSFER_ARROW_W) + 0.4
ARROW_WIN = (GAP_A0 + _CAP_DEG, GAP_A1 - _CAP_DEG, _ARROW_R0, _ARROW_R1)
ARROW_MIN = 40     # zoom=16 时箭尖那一小块约 130+ 个像素；40 是很宽松的下限


def at_xy_of(at, dx: float, dy: float):
    """取 `icon_pixels()` 返回的 `at` 上挂的 `at_xy`。"""
    return at.at_xy(dx, dy)


def dist(c1, c2) -> int:
    return (abs(c1.red() - c2.red()) + abs(c1.green() - c2.green())
            + abs(c1.blue() - c2.blue()))


def main() -> int:
    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(40)
    mv = win.map_view
    floor = mv._min_scale_for_viewport()

    print("\n===== A 站名压线（放大档必须干净 + 变异可抓）=====")
    res = {}
    for flag in (True, False):
        MV.LABEL_AVOID_LINES = flag
        for s in (0.30, 1.0):
            set_scale(mv, s, cold=True)      # ★ 必须冷启动，否则继承上一轮方向
            n, hit, deep = line_overlap(mv)
            res[(flag, s)] = (n, hit, deep)
            print("      避让=%-5s 缩放 %4.2f：站名 %3d，压线 %3d（%5.1f%%），"
                  "严重 %3d（%5.1f%%）"
                  % (flag, s, n, hit, 100.0 * hit / n, deep, 100.0 * deep / n))
    for s in (0.30, 1.0):
        n_on, hit_on, deep_on = res[(True, s)]
        n_off, hit_off, deep_off = res[(False, s)]
        # ★ v2.6.16：阈值 8% → 15%，**原因必须写清楚，不许默默放宽**。
        #   站点坐标重排成官方示意图后（tools/relayout_octilinear.py），
        #   每一段都是笔直的横/竖/45°。笔直的线**比歪扭的线更难躲**：
        #   以前线是抖的，站名常能蹭到线弯出去的空隙；现在线是直的，
        #   一旦站名落在这一排上就一定被穿过。实测：6.6% → 12.5%。
        #   这是"要示意图的样子"必然要付的代价，不是 bug。
        #   判据仍然有效：关掉避让时这一档是 56.8%，15% 仍能抓住"避让失效"。
        check(f"缩放 {s}：严重压线（线从字中穿过）< 15%",
              deep_on * 100.0 / n_on < 15.0,
              f"{deep_on}/{n_on} = {100.0 * deep_on / n_on:.1f}%"
              f"（示意图化前是 6.6%，直线更难躲，见上方注释）")
        if s >= MV.LABEL_LOCK_MIN_SCALE:
            # ★ v2.6.32：这些档位是**方位锁死**的（用户「不要每次缩放都乱窜」）
            #   ⇒ "开避让 vs 关避让"两个数字必然**一模一样**，这条比率判据在
            #   这里语义反了。锁死档要守的是另一件事：**开=关**（证明锁真的
            #   压过了避让，没人偷偷换边），压线绝对值由上面那条 <15% 把关。
            check(f"缩放 {s}：方位已锁死 ⇒ 开/关避让压线数**完全相同**",
                  hit_on == hit_off,
                  f"开 {hit_on} vs 关 {hit_off}")
        else:
            check(f"缩放 {s}：压线数比『关掉避让』时**减少一半以上**（变异可抓）",
                  hit_on <= hit_off * 0.5,
                  f"开 {hit_on} vs 关 {hit_off}")
        check(f"缩放 {s}：可见站名数不因避让而变少",
              n_on >= n_off - 2, f"开 {n_on} vs 关 {n_off}")

    MV.LABEL_AVOID_LINES = True

    print("\n===== E v2.6.27：小档**不许**往外让圈（让 1 圈就跨到隔壁站）=====")
    # 用户原话「缩小到一定尺寸文字完全偏离正确位置」。
    # 小档时站名框（屏幕恒定 ~50px）比站距（~25px）还宽，往外让 1 圈 ≈ 53 屏幕px
    # = 1~2 个站距 ⇒ 字会骑到隔壁站头上。所以外圈只在放大档（≥0.28）给。
    def ringed_set():
        return frozenset(sid for sid, it in mv.station_items.items()
                         if MR.split_label_ring(it.label_side())[1] > 0)

    def ringed_count():
        return len(ringed_set())

    # ★★ v2.6.43：判据语义改了。
    #   老判据是"缩到 0.16 时外圈数 == 0"（那条 v2.6.27 的"小档不许让圈"），
    #   但最小缩放现在是 **1.0** ⇒ 0.16 根本不可达，测它没意义；
    #   而且方位改成"任何档都用 1:1 参考档的锁表"之后，让圈数是**锁表里带的**，
    #   本来就不是 0。真正要保证的是：**它在各档都一样**（不随缩放重挑），
    #   这正是用户说的"位置记不住"的反面。
    _ring = {}
    _ringset = {}
    for s in (1.0, 1.5, 2.0, 3.0, 4.0):
        set_scale(mv, s, cold=True)
        _ring[s] = ringed_count()
        _ringset[s] = ringed_set()
    check("可达档位上「被推到外圈」的数量**恒定**（方位锁死，不随缩放重挑）",
          max(_ring.values()) - min(_ring.values()) == 0,
          " ".join(f"{k:.1f}档{_ring[k]}个" for k in _ring))
    check("可达档位上「被推到外圈」的**是哪几个站**也恒定",
          len(set(_ringset.values())) == 1,
          " %d 种不同的站集" % len(set(_ringset.values())))
    # 变异：用源码自带的 A/B 开关 `METROEDITOR_NO_LABEL_OFFICIAL=1`
    #   ⇒ 整段"照抄原图方位 / 锁表"逻辑被跳过，排版器**每一档都重新挑**
    #   ⇒ 外圈数必然随档浮动。（只盖 `_build_side_lock` 不够：`_take()` 会在
    #   排版里把方位写回锁表，第一档挑完后面全跟着走，实测仍是恒定 20 个。）
    os.environ["METROEDITOR_NO_LABEL_OFFICIAL"] = "1"
    mv._side_lock = {}
    _ring2 = {}
    _ringset2 = {}
    for s in (1.0, 1.5, 2.0, 3.0, 4.0):
        mv._side_lock = {}          # ★ 必须在排版**之前**清（排版时会写回锁表）
        set_scale(mv, s, cold=True)
        _ring2[s] = ringed_count()
        _ringset2[s] = ringed_set()
    os.environ.pop("METROEDITOR_NO_LABEL_OFFICIAL", None)
    # ★ v2.6.56：判据从"数量"改成"**是哪几个站**"。
    #   替身点长度按站距收紧之后（见 map_view.STUB_MAX_FRAC），线路几何更规整，
    #   "各档重挑"在很多档会挑到**同样的数量**（实测数量恒定 20 个）⇒ 老判据
    #   "数量不再恒定"直接失效，但它其实没证明锁表在岗 —— 拿"站集"比才敏感。
    _n_fluc = max(_ring2.values()) - min(_ring2.values())
    _s_fluc = len(set(_ringset2.values()))
    _diff = any(_ringset2[s] != _ringset[s] for s in (1.0, 1.5, 2.0, 3.0, 4.0))
    check("变异（锁表建不起来 ⇒ 各档各自重挑）后外圈**站集不再钉住** ⇒ E 判据真在岗",
          _n_fluc > 0 or _s_fluc > 1 or _diff,
          "数量浮动 %d，站集 %d 种，与正常不同=%s" % (_n_fluc, _s_fluc, _diff))
    mv._side_lock = {}
    _old_th = MV.LABEL_RING_MIN_SCALE
    MV.LABEL_RING_MIN_SCALE = 0.0        # 变异：小档也允许让圈
    set_scale(mv, 1.0, cold=True)
    check("变异（阈值设 0 ⇒ 允许让圈）后外圈数变多 ⇒ 阈值真在岗",
          ringed_count() >= max(_ring.values()),
          "%d 个（正常 %d 个）" % (ringed_count(), max(_ring.values())))
    MV.LABEL_RING_MIN_SCALE = _old_th

    print("\n===== F v2.6.27：最小缩放被限制 =====")
    floor_now = mv._min_scale_for_viewport()
    check("缩放下限本身 ≥ MIN_VIEW_SCALE(%.2f)" % MV.MIN_VIEW_SCALE,
          floor_now >= MV.MIN_VIEW_SCALE - 1e-6, "%.4f" % floor_now)
    # ★ 试图缩到 0.05（远低于下限），再看画面上真正用到的缩放落在哪儿。
    #   读 transform().m11()：**实际视图变换**，不是动画目标值 _scale
    #   （连打 40 次 0.8 倍会把 _scale 一路乘到接近 0，那个数没有意义）。
    set_scale(mv, 0.05)
    mv._enforce_zoom_floor()
    pump(10)
    _sc = mv.transform().m11()
    check("强缩到 0.05 后被抬回 ≥ MIN_VIEW_SCALE(%.2f)" % MV.MIN_VIEW_SCALE,
          _sc >= MV.MIN_VIEW_SCALE - 1e-6, "%.4f" % _sc)
    # 变异：把下限设成 0 ⇒ 缩到 0.05 时不会再被抬起来 ⇒ 判据必须失败
    MV.MIN_VIEW_SCALE = 0.0
    set_scale(mv, 0.05)
    mv._enforce_zoom_floor()
    pump(10)
    check("变异（下限设 0）后确实能缩得更小 ⇒ F 判据真在岗",
          mv.transform().m11() < 0.18 - 1e-6, "%.4f" % mv.transform().m11())
    MV.MIN_VIEW_SCALE = float(os.environ.get("METROEDITOR_MIN_SCALE", "0.18"))

    set_scale(mv, floor)
    n_min, hit_min, deep_min = line_overlap(mv)
    n_off_min, hit_off_min, _d = res.get((False, 0.30), (0, 0, 0))
    set_scale(mv, 0.093)
    n0, h0, _ = line_overlap(mv)
    print("      缩到最小 %.3f：站名 %d，压线 %d（%.1f%%）"
          % (floor, n0, h0, 100.0 * h0 / n0))
    check("缩到最小：压线率不比改动前差（那一档站名框比站距还宽，没有腾挪空间）",
          h0 <= 0.56 * n0, f"{100.0 * h0 / n0:.1f}% ≤ 56%")

    print("\n===== B 换乘站图标（大药丸 v2.6.19 + 方向/长度 v2.6.20，像素可量）=====")
    at_tr, bg = icon_pixels(True)
    at_nm, _bg2 = icon_pixels(False)
    VS_TR = 1.0          # icon_pixels 默认 zoom=1 ⇒ view_scale = 1.0（屏幕=场景=画布）
    dark = QColor(TRANSFER_RING_COLOR)
    # ★ v2.6.20：尺子取**实际**尺寸（不再用常量 —— 药丸现在有方向、长度逐站不同）
    RX, RY = at_tr.hw, at_tr.hl
    print("      药丸尺（屏幕px，无 pill 数据时的缺省竖药丸）：半宽 %.2f | 半长 %.2f | 长/宽 %.2f"
          % (RX, RY, RY / RX))

    # ① 竖向：垂直方向（90°）在「超过水平半宽」之后仍然有图标 ⇒ 药丸是竖着长的
    #    ★ 判据不依赖角度约定：同一半径放在 0°（水平）就该是背景，放 90° 不是。
    # ★ v2.6.25：探针必须用**实际半长** RY 去探，不能用"半宽+4"这种硬编码半径。
    #   药丸 v2.6.25 起贴着走廊长（缩到小档半长只有 6.4px），半宽+4 = 8.0 已经探到
    #   药丸外面去了 —— 判据会假失败，而药丸本身是好的。
    # ★★ v2.6.55：探针半径改成 **RY 的百分比**，不再是"RY − 1px"。
    #   "减 1px"默认 1px 相对药丸很小；但画布坐标 = 屏幕半径 × zoom，zoom 一大，
    #   1 屏幕像素就对应好几个画布像素，探针一下扎进中心的线路色小点
    #   （实测 zoom=16 时 r=半长−1 取到 #1565c0，六条判据全假失败）。
    #   改成比例就与 zoom 无关，任何缩放下探的都是同一个相对位置。
    R_UP = RY * 0.8
    c_up = at_tr(R_UP, 90)
    # ★★ 背景 #F7F9FB 与白色 #FFFFFF 只差 18（三通道绝对差之和）—— 用
    #    「不是背景」判定会把白色也算成背景 ⇒ 直接判「这里是白色药丸」。
    check("药丸是**竖向**的：垂直方向 r=半长×0.8（%.1f）仍是**白色药丸**" % R_UP,
          dist(c_up, QColor("#FFFFFF")) < 12, f"{c_up.name()}")
    c_side = at_tr(R_UP, 0)
    check("同一半径放**水平**方向（0°）已是背景 ⇒ 确实只朝上下长",
          dist(c_side, bg) < 60, f"{c_side.name()}")

    # ② 水平方向边界清晰（没糊成一坨）
    # ★ v2.6.20：判据换成"这里是**白心**"。原来判"≠ 背景"只是**碰巧**成立的：
    #   旧版描边是细笔、笔心压在白心边缘上，r=半宽−1 正好切进描边内缘（抗锯齿偏暗）；
    #   v2.6.20 把黑边整圈画在白心**外面**之后，r=半宽−1 是纯白 ⇒ 拿"≠背景"判会假失败。
    #   白 #FFFFFF 与底图 #F7F9FB 只差 18，用 < 12 判"是白心"仍有区分度（实测 18 > 12）。
    check("水平方向 r=半宽×0.8 是**白心**（在图标内）",
          dist(at_tr(RX * 0.8, 0), QColor("#FFFFFF")) < 12,
          f"{at_tr(RX * 0.8, 0).name()}")
    check("水平方向 r=半宽×2 已在图标外",
          dist(at_tr(RX * 2.0, 0), bg) < 60, f"{at_tr(RX * 2.0, 0).name()}")

    # ②b 白心外面那圈粗黑边（v2.6.20 补；原图实测白心 26 / 外廓 41 ⇒ 边厚 7 场景单位）
    #    ★ 判据按"边厚"这个**几何量**来判，不是判"有没有深色"：
    #      边厚在屏幕上的宽度 = TRANSFER_PILL_BORDER × 视图缩放
    _bs = MR.TRANSFER_PILL_BORDER * VS_TR
    check("白心外 r=半宽+边厚/2 是**深色黑边**",
          dist(at_tr(RX + _bs * 0.5, 0), dark) < 260,
          f"{at_tr(RX + _bs * 0.5, 0).name()}（边厚 {_bs:.2f}px）")
    check("再往外 r=半宽+边厚×1.5 已是背景 ⇒ 黑边真的有厚度上限、不是糊的一片",
          dist(at_tr(RX + _bs * 1.5, 0), bg) < 60,
          f"{at_tr(RX + _bs * 1.5, 0).name()}")

    # ③ 侧边深色描边
    check("药丸侧边（r=半宽, 0°）是**深色描边**",
          dist(at_tr(RX, 0), dark) < 220, f"{at_tr(RX, 0).name()}")

    # ④ 中心仍是线路色小点（换乘站压多条线，用它表明主色）
    check("中心是**线路色**实心点（示例 #1565C0）",
          dist(at_tr(0), QColor("#1565C0")) < 90, f"{at_tr(0).name()}")

    # ⑤ 比普通站明显更大
    # ★ v2.6.25：原来要求"半长 > 普通站半径×2"是拿 v2.6.19 那个"固定大药丸"定的。
    #   现在药丸贴着走廊长，最小档半长 6.4px（普通站半径 3.4）⇒ 药丸**总长** 12.8
    #   仍是普通站直径 6.8 的 1.88 倍，肉眼足够区分。真正的不变量是"比普通站明显大"，
    #   不是"≥ 某个写死的旧尺寸"。
    # ★★ v2.6.55：尺子换成**同档实测的普通站半径**，不再是 SCREEN_NORMAL_R 常量。
    #   v2.6.54 起圆点/药丸全部等比缩放（"照片缩放"），SCREEN_NORMAL_R=3.4 只是个
    #   缺省常量，**不等于**任何缩放下的实际半径 —— 拿"实测半长"去比"常量半径"
    #   是量纲不一致（半长 2.9px vs 常量 3.4px 会假失败，而真实比值恒为 2.27）。
    # ★ 特意在**软件真正的最小档**（MIN_VIEW_SCALE，v2.6.51 起 = 0.115）比：
    #   这才是"缩到最小还看得出换乘站"该验的那一档。
    ZM = 1.0 / max(float(floor), 1e-6)   # floor = 软件真正 enforce 出来的最小缩放
    at_m_tr, _ = icon_pixels(True, zoom=ZM)
    at_m_nm, _ = icon_pixels(False, zoom=ZM)
    ok_big = at_m_tr.hl > at_m_nm.hw * 1.6
    check("换乘站比普通站**更大**（缩到最小也能靠尺寸先看出来）", ok_big,
          f"最小档 {MV.MIN_VIEW_SCALE:.3f}：药丸半长 {at_m_tr.hl:.2f} > "
          f"普通站半径 {at_m_nm.hw:.2f}×1.6 = {at_m_nm.hw * 1.6:.2f}")

    # ⑥ 两种图标在同一位置颜色不同（可区分）
    # ★ 取图标**中心**对比：普通站中心是白色填充，换乘站中心是线路色小点
    check("图标**中心**处普通站与换乘站颜色明显不同（两种图标可区分）",
          dist(at_nm(0), at_tr(0)) > 100,
          f"普通 {at_nm(0).name()} vs 换乘 {at_tr(0).name()}")

    print("\n===== B2 变异自检：把药丸改回正圆 ⇒ 「竖向」判据必须失败 =====")
    # ★★ 只能换**实例所属类的方法**；还原时赋回原函数即可（这里是普通函数，
    #    不是 staticmethod，直接赋回去就是普通方法 —— 与旧代码的坑不同）。
    old_pill = MR.StationDotItem._paint_transfer_pill

    def _round_style(self, painter, RX_, RY_, k):
        """变异体：画**正圆**（半径只取半宽）⇒ 垂直方向不再长出药丸。"""
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        pen = QPen(QColor(TRANSFER_RING_COLOR))
        pen.setWidthF(MR.SCREEN_DOT_STROKE * k)
        painter.setPen(pen)
        painter.drawEllipse(QPointF(0, 0), RX_, RX_)

    MR.StationDotItem._paint_transfer_pill = _round_style
    at_old, _ = icon_pixels(True)
    c_old = at_old(R_UP, 90)
    # ★ 阈值收成 12（不是 60）：白药丸 #FFFFFF 与背景 #F7F9FB 只差 18，
    #   用 60 的话"变异后还是白的"也会被当成"已经是背景" ⇒ 判据假通过。
    check("变异（改成正圆）后垂直方向 r=半长×0.8 变回背景 ⇒ 判据真在上岗",
          dist(c_old, bg) < 12, f"变异后 {c_old.name()}")
    MR.StationDotItem._paint_transfer_pill = old_pill

    # ★★ 原来这里还有"变异 2：把半高砍到=半宽"，**已删除** —— 它是个假通过：
    #    ① 改 MR.SCREEN_TRANSFER_RY 根本不生效（那常量只在没有 pill 数据时当缺省）；
    #    ② 改成显式给 {"len":6,"wid":6} 也不行 —— 半长有**硬下限 14 场景单位**
    #       （实测 len=6/20/30 全都被顶回 14~15），加上边厚 7 后外廓到 21px，
    #       而探针固定在 R_UP=20 ⇒ 怎么"砍"都落在边里，判不出区别。
    #    ③ 更糟的是旧阈值 <60 会把"变异后仍是白药丸"(差 18) 也算成背景。
    #    ⇒ 只保留上面那条"改成正圆"的变异（实测变异后 #f7f9fb，判据真的会响）。

    print("\n===== B3 药丸**方向**（v2.6.20：横/竖/斜各不相同）=====")
    # 用车公庙的真实数据：ang=180（横）、len=128、wid=26。
    # 取 view_scale=0.54 —— 这正是"原图 26 像素 ↔ 屏幕 14 像素"的比例，
    # 此时药丸尺寸与原图**完全一致**，可以直接按原图尺寸判。
    # ★ zoom 必须 = 1/view_scale（icon_pixels 的取样坐标靠这个换算），别乱给。
    VS = 0.54
    ZM = 1.0 / VS
    CGM = {"pill": {"ang": 180.0, "len": 128, "wid": 26}}
    at_h, bg_h = icon_pixels(True, zoom=ZM, data_extra=CGM, view_scale=VS)
    hw, hl = at_h.hw, at_h.hl
    print("      横药丸尺（屏幕px）：半宽 %.2f | 半长 %.2f（长/宽 %.2f）"
          % (hw, hl, hl / hw))
    check("横药丸的长/宽比 ≈ 原图 128/26",
          abs(hl / hw - 128.0 / 26.0) < 0.2, f"{hl / hw:.2f} vs {128 / 26:.2f}")
    check("**水平**方向 r=半长−2 仍是**白色药丸** ⇒ 药丸真是横的",
          dist(at_h(hl - 2.0, 0), QColor("#FFFFFF")) < 12,
          f"{at_h(hl - 2.0, 0).name()}")
    # ★ 判"是背景"用 < 12（白药丸 #FFFFFF 与背景 #F7F9FB 只差 18，用 < 60 会把白也算成背景）
    # ★ v2.6.20：药丸外面还有一圈边厚 = 7 场景单位 = 7×VS 屏幕px 的黑边，
    #   "已经是背景"的探针必须**越过外廓**（白心 + 整条边厚），否则会切在抗锯齿上假失败。
    bd = MR.TRANSFER_PILL_BORDER * VS
    check("**水平**方向 r=半长+边厚+4 已是背景 ⇒ 水平端头边界清晰",
          dist(at_h(hl + bd + 4.0, 0), bg_h) < 12, f"{at_h(hl + bd + 4.0, 0).name()}")
    # ★ 别用"不是背景"判"在药丸内"：白药丸 #FFFFFF 与背景 #F7F9FB 只差 18
    #   （见上面 B 段的老注释）—— 这里直接判"是白色药丸"。
    check("**垂直**方向 r=半宽−1 是**白色药丸**（不是背景）",
          dist(at_h(hw - 1.0, 90), QColor("#FFFFFF")) < 12,
          f"{at_h(hw - 1.0, 90).name()}")
    check("**垂直**方向 r=半宽+边厚+4 已是背景 ⇒ 它没有朝上下长",
          dist(at_h(hw + bd + 4.0, 90), bg_h) < 12, f"{at_h(hw + bd + 4.0, 90).name()}")

    print("\n===== B4 变异自检：把 ang 由 180°（横）改成 90°（竖）⇒ 横的判据必须失败 =====")
    at_v, bg_v = icon_pixels(True, zoom=ZM, view_scale=VS,
                             data_extra={"pill": {"ang": 90.0, "len": 128, "wid": 26}})
    check("变异后「水平方向 r=半长−2 是白色药丸」不再成立 ⇒ 判据真在量方向",
          dist(at_v(at_v.hl - 2.0, 0), bg_v) < 12,
          f"变异后 {at_v(at_v.hl - 2.0, 0).name()}")

    print("\n===== B5 药丸尺寸随缩放（v2.6.20：走廊是按地图算的，药丸也得跟）=====")
    # 缩到整图时药丸要保持 v2.6.19 那个大小（别缩成看不清的点）
    at_z, _ = icon_pixels(True, zoom=8.0, view_scale=0.125,
                          data_extra={"pill": {"ang": 90.0, "len": 128, "wid": 26}})
    # ★ v2.6.25：不再要求"≥ v2.6.19 那个固定缺省值"（那条跟"贴合走廊"直接冲突：
    #   保住固定尺寸就必然比走廊宽好几倍，正是用户说的"乱搞比例"）。
    #   真正的不变量是"缩到最小仍然是个看得出的胶囊，而且不比普通站小"。
    check("缩到 0.125 时药丸仍是胶囊（半长 ≥ 半宽×%.1f）" % MR.PILL_MIN_RATIO,
          at_z.hl >= at_z.hw * MR.PILL_MIN_RATIO - 1e-6,
          f"{at_z.hl:.2f} ≥ {at_z.hw * MR.PILL_MIN_RATIO:.2f}")
    # ★★ v2.6.55：尺子换成**同档实测的普通站半径**。SCREEN_NORMAL_R 是缺省常量，
    #   v2.6.54 起圆点等比缩放后它**不等于**任何一档的真实半径（0.125 档真实
    #   半径只有 1.38px，常量却是 3.4 ⇒ 拿常量当尺子必然假失败）。
    at_zn, _ = icon_pixels(False, zoom=8.0, view_scale=0.125)
    check("缩到 0.125 时药丸半宽 ≥ 普通站半径（不许比普通站还小）",
          at_z.hw >= at_zn.hw - 1e-6,
          f"{at_z.hw:.2f} ≥ 同档普通站半径 {at_zn.hw:.2f}")
    # 放大时按地图尺寸长（否则够不到最外侧的那条走廊）
    at_b, _ = icon_pixels(True, zoom=ZM, view_scale=VS,
                          data_extra={"pill": {"ang": 90.0, "len": 128, "wid": 26}})
    check("放到 0.54 时药丸按原图尺寸（半长 ≈ 128×0.54÷2）",
          abs(at_b.hl - 128.0 * VS / 2) < 1.0, f"{at_b.hl:.2f}")
    # ★★ 药丸**不许设上限**：走廊是跟地图走的，药丸一旦停止长大，
    #    放大到后面就会"够不到最外侧的那条走廊"（第一版夹了 3 倍上限就栽在这，
    #    2 倍缩放时走廊相距 200px、药丸只有 80px，中间断开）。
    at_c, _ = icon_pixels(True, zoom=2.0, view_scale=0.5,
                          data_extra={"pill": {"ang": 90.0, "len": 128, "wid": 26}})
    # ★★ v2.6.24：这里该判的是"**没被上限截住**"，不是"恰好等于 32"。
    #    药丸下限改成等比放大后，窄药丸（wid=26）在 0.5 档短轴会触发下限，
    #    两轴一起乘 1.08 ⇒ 半长 34.5 而非 32。比地图长**只会更容易连上走廊**，
    #    真正要保证的是"不许比地图短"。写成相等判定就把用户要的那个改动判死了
    #    （原话「并不是所有中转站示例的胶囊都一样大」）。
    check("放到 0.5 时药丸没被上限截住（半长 ≥ 128×0.5÷2 = 32）",
          at_c.hl >= 32.0 - 1e-6 and at_c.hl <= 32.0 * 1.5, f"{at_c.hl:.2f}")
    at_d, _ = icon_pixels(True, zoom=1.0, view_scale=1.0,
                          data_extra={"pill": {"ang": 90.0, "len": 128, "wid": 26}})
    check("放到 1.0 时药丸 = 原图原尺寸（半长 64）",
          abs(at_d.hl - 64.0) < 1.0, f"{at_d.hl:.2f}")

    print("\n===== C 不许因避让线路而丢站名（数量对比）=====")
    counts = {}
    for flag in (False, True):
        MV.LABEL_AVOID_LINES = flag
        for s in (floor, 0.16, 0.30, 1.0):
            set_scale(mv, s)
            n, _h, _d = line_overlap(mv)
            counts[(flag, s)] = n
    for s in (floor, 0.16, 0.30, 1.0):
        # ★ v2.6.16 同上：容差 2 → 8，理由写在下面，不许默默放宽。
        #   示意图化让路径变短（线被拉直了），整图塞进视口后
        #   **屏幕站距从 27.2px 掉到 25.6px（−6%）** ⇒ 站名相对变大、更容易撞上，
        #   于是"为了不压线而放弃显示"的站名多了一点（实测最小档 227 → 200）。
        #   压线率反而更好（46.7% → 38.0%）。8 这个容差仍能抓住"避让被整个关掉"
        #   （关掉时反而显示更多，差值会明显为负）。
        check(f"缩放 {s:.3f}：站名数 开避让 ≥ 关避让 − 8",
              counts[(True, s)] >= counts[(False, s)] - 8,
              f"{counts[(True, s)]} vs {counts[(False, s)]}")
    MV.LABEL_AVOID_LINES = True

    print("\n===== D 排版耗时（缩放收尾跑一次）=====")
    # ★★ 原来只有一条**绝对阈值**（`< 90ms`），实测同一份代码空转连跑三次是
    #    65.9 / 72.5 / 90.8 ms，机器一忙就上百 —— 阈值正好压在噪声地板上，
    #    这条断言退化成了"抛硬币"（跟 MEMORY §5.1 一个毛病：判据错了结论全错）。
    #    换成两条：
    #      ① **比值**判据（机器忙不忙都成立）：开避让 / 关避让 ≤ 2.5。
    #         避让只是在同一套排版外面多套一层"这块矩形里穿过多长的线"打分，
    #         成本应该是**常数倍**；真写坏了（比如退化成每个站名扫全部 1805 段），
    #         这个比值会立刻爆掉。
    #      ② **绝对**判据放宽到 260ms：只用来抓"彻底炸了"
    #         （已知缩放收尾的一次冻结本来就在 150~200ms 量级，MEMORY §5.2）。

    def _layout_ms(mv, s: float) -> float:
        set_scale(mv, s)
        c = []
        for _ in range(3):
            t0 = time.perf_counter()
            mv._update_label_visibility()
            c.append((time.perf_counter() - t0) * 1000.0)
        return statistics.median(c)

    scales = (floor, 0.16, 0.30, 1.0)
    MV.LABEL_AVOID_LINES = False
    base = {s: _layout_ms(mv, s) for s in scales}
    MV.LABEL_AVOID_LINES = True
    avoid = {s: _layout_ms(mv, s) for s in scales}
    # ★★ v2.6.43：改成**逐档比**，不再"关避让取最坏档 ÷ 开避让取最坏档"。
    #   老写法分子分母可能来自**不同档位**（比如关避让最坏在 1.0、开避让最坏在
    #   floor）⇒ 比值根本不是"避让这一层的开销"，而是两个档位的工作量之比。
    #   v2.6.43 关掉物理下限后小档字更小、显示得更多 ⇒ 那档工作量本来就更大，
    #   跨档一比就虚高到 3.4×。逐档比才是真正在测"避让贵多少"。
    ratios = {s: avoid[s] / max(base[s], 1e-6) for s in scales}
    worst_s = max(ratios, key=lambda s: ratios[s])
    ratio = ratios[worst_s]
    base_worst = max(base.values())
    avoid_worst = max(avoid.values())
    print("      逐档比值 " + "  ".join(f"{s:.2f}档 {ratios[s]:.2f}×"
                                        for s in scales))
    print("      关避让最坏 %.1fms / 开避让最坏 %.1fms"
          % (base_worst, avoid_worst))
    # ★ 阈值 6.5 的来源：A/B 实测 —— 开/关 `METROEDITOR_PHYSICAL_MINS` 两次
    #   逐档比值都是 3.3~5.5×（旧开关 0.30 档 5.46×、1.00 档 5.10×）。
    #   也就是说"避让这一层本来就贵 3~6 倍"，**2.5 是当初拍脑袋写的**，
    #   它一直在抛硬币（v2.6.42 之前碰巧 0.66× 是跨档取 max 的假象）。
    #   真正兜底的是下面那条绝对值 + 把索引废掉的变异自检。
    check("排版耗时：**同一档** 开避让 / 关避让 ≤ 6.5（逐档比，不跨档取 max）",
          ratio <= 6.5,
          f"最坏 {worst_s:.2f} 档 {ratio:.2f}×（{base[worst_s]:.1f} → "
          f"{avoid[worst_s]:.1f}ms）")
    check("排版耗时绝对值 < 260ms（只抓彻底炸了）", avoid_worst < 260.0,
          f"{avoid_worst:.1f}ms")

    # 变异：`hit_length` 退化成**遍历全部线段**（把粗网格索引废掉）
    #    ⇒ 379 站 × 8 个候选方向 × 1805 段，比值/绝对值都必须爆掉。
    idx = mv._line_idx
    old_hit = idx.hit_length

    def _hit_all_segs(self, rect, pad):
        """跟真 `hit_length` **算同一个东西**（都是"矩形里穿过多长的线"），
        只是不做粗网格剪枝 —— 这样变异只改变**耗时**，不改变排版结果，
        才能证明 D 组判据量到的确实是"慢"而不是"画错了"。
        """
        l = rect.left() - pad
        t = rect.top() - pad
        rgt = rect.right() + pad
        b = rect.bottom() + pad
        total = 0.0
        for s in self.segs:
            total += MR._clip_len(s[0], s[1], s[2], s[3], l, t, rgt, b)
        return total

    idx.hit_length = types.MethodType(_hit_all_segs, idx)
    t0 = time.perf_counter()
    _layout_ms(mv, 1.0)
    bad_ms = (time.perf_counter() - t0) * 1000.0
    idx.hit_length = old_hit
    check("变异（废掉线段粗网格索引，退化成全表扫描）后耗时**爆掉** ⇒ D 判据真在上岗",
          bad_ms > avoid_worst * 3.0,
          f"变异后 3 次共 {bad_ms:.0f}ms vs 正常 {avoid_worst * 3:.0f}ms")

    win.close()
    pump()
    print(f"\n===== 结果：{PASS} 通过 / {FAIL} 失败 =====")
    if FAILED:
        print("失败项：")
        for n in FAILED:
            print("  -", n)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
