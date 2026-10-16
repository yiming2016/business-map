# -*- coding: utf-8 -*-
"""自动追踪：让画出来的线**照着官方原图那条真的线**走（甲），
以及拖站点时**自动吸到原图走廊上**（乙）。

背景（用户原话）：「我还是无法让线条跟随下方的底图」。

★ 关键前提：官方原图 8000×8000，**1 个原图像素 == 1 个场景单位**
  （见 map_view.UNDERLAY_SCENE）⇒ 原图坐标可以直接当场景坐标用，不需要任何变换。

★ 数据从哪来：`data/trace_cloud.json`，由 `tools/build_trace_cloud.py` 在构建期
  用 numpy/PIL/scipy 从 `assets/shenzhen_metro.png` 抽好 —— **运行时不需要
  numpy/PIL**（打包体积不涨、启动不拖慢）。
  {"<线号>": [[x, y], ...]}  是每条线走廊的**中心线点云**（不是整条 22px 宽的带子）。

★ 为什么用点云 + A*，而不是直接对像素做：点云是稀疏的（每线 0.5k~4k 个点），
  纯 Python 就能跑；A* 出来的路径天然沿着中心线，不会被走廊宽度带偏。

三件事：
  deviation()   这一站离官方走廊有多远（像素）—— 「偏差提示」
  snap()        把一个点吸到最近的官方走廊点上（乙：拖动吸附）
  trace()       沿官方走廊把 A→B 的路径走出来（甲：自动描线）
"""
from __future__ import annotations

import heapq
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

CLOUD_FILE = "trace_cloud.json"

# 点云是 CELL=8 抽的，连边上限取 2 格 ⇒ 对角线上的邻居也连得上（8*√2≈11.3 < 16）
LINK = 16.0
CELL_IDX = 64          # 最近邻查询用的粗网格边长
# ★ 跨缺口搭桥：官方原图里**别的线从这条线上面横穿过去**时，会把这条线的颜色
#   盖掉一条（宽 ≈ 那条线的线宽 22~30px），走廊点云就断成两截 —— 实测 1号线
#   3280 个点里"大新"那一段只连着 217 个，A* 直接走不通。
#   同理换乘站的白药丸也会把走廊盖掉一截。
#   ⇒ 允许在 BRIDGE 距离内跨过去，但代价加 BRIDGE_COST（很贵），
#     这样 A* 只在"真的没路"时才搭桥，不会抄近路穿过并行走廊。
BRIDGE = float(os.environ.get("METROEDITOR_TRACE_BRIDGE", "80.0"))
BRIDGE_COST = float(os.environ.get("METROEDITOR_TRACE_BRIDGE_COST", "400.0"))
SNAP_MAX = float(os.environ.get("METROEDITOR_TRACE_SNAP_MAX", "260.0"))
# 描线路径两端各掐掉多少像素：站点图标（白药丸/黑圈）本来就盖住了走廊，
# 不掐掉的话起手会先往回勾一个小倒钩。
TRIM_END = 45.0
# ★★ v2.6.61：4.0 → 14.0。用户原话「现在的线路是凹凸不平的，本该是直线的线路，
#   使用自动描线…并不能很好的绘制出来」。
#   病因：点云是 CELL=8 抽的，A* 沿网格走出来的路径是**8px 一级的锯齿**，
#   RDP=4 几乎一个锯齿点都不删 ⇒ 密密麻麻的碎点，渲染时每个碎点还各倒一个圆角
#   ⇒ 一条直线被画成一串小波浪（实测 1 号线一段能描出 20+ 个点）。
#   RDP=14 把锯齿压掉（官方线宽 30 ⇒ 简化误差 ≤14 仍在带子内，不会脱线）。
RDP_EPS = float(os.environ.get("METROEDITOR_TRACE_RDP", "14.0"))
# 还要再过两道：① 删掉"三点几乎共线"的中间点（锯齿的另一种形态）；
#              ② 相邻点最小间距 —— 太密的点会被判"折点扎堆"（阈值 35px）。
COLLINEAR_EPS = float(os.environ.get("METROEDITOR_TRACE_COLLINEAR", "8.0"))
MIN_STEP = float(os.environ.get("METROEDITOR_TRACE_MIN_STEP", "42.0"))
# ---- v2.6.62：「探测弧度」+ 段级官方体检（Ctrl + 悬停某段 ⇒ 双击/右键菜单）----
# 「探测弧度」= 先沿官方点云把 A→B 走出来，再**平滑一次**（按弧长分桶取中位）。
#   为什么还要平滑：官方位图的拐弯是**圆角 + 抗锯齿**，中心线会左右摇摆，
#   逐点照抄就把一个圆角抄成一串小碎折（就是用户说的"凹凸不平"）。
#   分桶取中位 = 沿弧长每 ~90px 取一个"中间位置" ⇒ 摇摆被平均掉，留下真弧。
SMOOTH_RDP = float(os.environ.get("METROEDITOR_TRACE_SMOOTH_RDP", "10.0"))
BUCKET_STEP = float(os.environ.get("METROEDITOR_TRACE_BUCKET", "90.0"))
DEV_SAMPLE = 25.0     # 量"这条线离底图多远"时，沿折线的采样步长
DEV_MAX_R = 800.0     # 采样点在本线点云里找不到邻居 ⇒ 记这个满分（= 脱线惩罚）

_cloud: Optional[Dict[str, List[List[float]]]] = None
_cloud_loaded = False
_graphs: Dict[str, "_Graph"] = {}


class _Graph:
    """一条线的中心线点云 + 邻接表（建一次，反复用）。"""

    __slots__ = ("pts", "idx", "cell", "nbr", "ncomp", "nbridge")

    def __init__(self, pts: Sequence[Sequence[float]], cell: float = CELL_IDX):
        self.pts = [(float(p[0]), float(p[1])) for p in pts]
        self.cell = float(cell)
        self.idx: Dict[Tuple[int, int], List[int]] = {}
        for i, (x, y) in enumerate(self.pts):
            k = (int(x // cell), int(y // cell))
            self.idx.setdefault(k, []).append(i)
        # 邻接：同格 + 周围 8 格，距离 ≤ LINK
        ln = LINK * LINK
        self.nbr: List[List[Tuple[int, float]]] = []
        for i, (x, y) in enumerate(self.pts):
            gx, gy = int(x // cell), int(y // cell)
            out = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in self.idx.get((gx + dx, gy + dy), ()):
                        if j == i:
                            continue
                        d2 = (self.pts[j][0] - x) ** 2 + (self.pts[j][1] - y) ** 2
                        if d2 <= ln:
                            out.append((j, math.sqrt(d2)))
            self.nbr.append(out)
        self._bridge()

    def _bridge(self) -> None:
        """把被"别的线横穿"切碎的走廊重新接起来（见 BRIDGE 的注释）。"""
        n = len(self.pts)
        if n < 2:
            return
        # 1) 连通分量编号
        comp = [-1] * n
        cid = 0
        for s in range(n):
            if comp[s] >= 0:
                continue
            stack = [s]
            comp[s] = cid
            while stack:
                c = stack.pop()
                for j, _ in self.nbr[c]:
                    if comp[j] < 0:
                        comp[j] = cid
                        stack.append(j)
            cid += 1
        self.ncomp = cid
        if cid < 2:
            return
        # 2) 跨分量的近邻 ⇒ 加一条"很贵"的边
        bcell = 48.0
        bidx: Dict[Tuple[int, int], List[int]] = {}
        for i, (x, y) in enumerate(self.pts):
            bidx.setdefault((int(x // bcell), int(y // bcell)), []).append(i)
        b2 = BRIDGE * BRIDGE
        added = 0
        for i, (x, y) in enumerate(self.pts):
            gx, gy = int(x // bcell), int(y // bcell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in bidx.get((gx + dx, gy + dy), ()):
                        if j <= i or comp[j] == comp[i]:
                            continue
                        d2 = (self.pts[j][0] - x) ** 2 + (self.pts[j][1] - y) ** 2
                        if d2 > b2:
                            continue
                        w = math.sqrt(d2) + BRIDGE_COST
                        self.nbr[i].append((j, w))
                        self.nbr[j].append((i, w))
                        added += 1
        self.nbridge = added

    def nearest(self, x: float, y: float, max_r: float = SNAP_MAX
                ) -> Optional[Tuple[int, float, float, float]]:
        """返回 (下标, px, py, 距离)；找不到（或超出 max_r）给 None。"""
        if not self.pts:
            return None
        best = None
        bd = max_r * max_r
        gx, gy = int(x // self.cell), int(y // self.cell)
        # 一圈圈往外扩，直到这一圈的"最近可能距离"已经大于当前最优
        for r in range(0, int(max_r // self.cell) + 2):
            if r > 0 and ((r - 1) * self.cell) ** 2 > bd:
                break
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if r > 0 and max(abs(dx), abs(dy)) != r:
                        continue          # 只扫这一圈的边框
                    for i in self.idx.get((gx + dx, gy + dy), ()):
                        px, py = self.pts[i]
                        d2 = (px - x) ** 2 + (py - y) ** 2
                        if d2 < bd:
                            bd = d2
                            best = (i, px, py, math.sqrt(d2))
            if best is not None and r >= 1 and ((r - 1) * self.cell) ** 2 > bd:
                break
        return best

    def astar(self, a: int, b: int) -> Optional[List[int]]:
        """点云图上 a→b 的最短路（A*，欧氏距离做启发）。"""
        if a == b:
            return [a]
        pts = self.pts
        tx, ty = pts[b]
        open_h = [(0.0, a)]
        g: Dict[int, float] = {a: 0.0}
        came: Dict[int, int] = {}
        closed = set()
        while open_h:
            _, cur = heapq.heappop(open_h)
            if cur in closed:
                continue
            if cur == b:
                break
            closed.add(cur)
            cx, cy = pts[cur]
            gc = g[cur]
            for j, w in self.nbr[cur]:
                if j in closed:
                    continue
                ng = gc + w
                if ng < g.get(j, 1e18):
                    g[j] = ng
                    came[j] = cur
                    jx, jy = pts[j]
                    heapq.heappush(open_h, (ng + math.hypot(jx - tx, jy - ty), j))
        if b not in came and b != a:
            return None
        path = [b]
        while path[-1] != a:
            p = came.get(path[-1])
            if p is None:
                return None
            path.append(p)
        path.reverse()
        return path


def _load() -> Dict[str, List[List[float]]]:
    global _cloud, _cloud_loaded
    if _cloud_loaded:
        return _cloud or {}
    _cloud_loaded = True
    _cloud = {}
    # ★ 找文件的顺序跟 `MapView._show_underlay()` 一模一样：先用户数据目录，
    #   再打包进去的那份（exe 只在"用户 data/ 是空的"时才从 _MEIPASS 铺初始文件，
    #   而 trace_cloud.json 不在 INITIAL_FILES 里 ⇒ 新装的机器上只有 _MEIPASS 里有）。
    cands = []
    try:
        from core.data_manager import DATA_DIR
        cands.append(Path(DATA_DIR) / CLOUD_FILE)
    except Exception:
        pass
    _mei = getattr(sys, "_MEIPASS", None)
    if _mei:
        cands.append(Path(_mei) / "data" / CLOUD_FILE)
    cands.append(Path(__file__).resolve().parent.parent / "data" / CLOUD_FILE)
    for p in cands:
        try:
            if p.is_file():
                _cloud = json.loads(p.read_text(encoding="utf-8")) or {}
                break
        except Exception:
            continue
    return _cloud


def available() -> bool:
    """点云在不在（没有就整个自动追踪功能静默关闭，不影响别的）。"""
    return bool(_load())


def cloud_of(line_id: str) -> List[List[float]]:
    return _load().get(str(line_id)) or []


def reload() -> None:
    """数据被换掉时清缓存。"""
    global _cloud, _cloud_loaded
    _cloud = None
    _cloud_loaded = False
    _graphs.clear()
    _cidxs.clear()


def _graph(line_id: str) -> Optional[_Graph]:
    lid = str(line_id)
    g = _graphs.get(lid)
    if g is None:
        pts = cloud_of(lid)
        if not pts:
            return None
        g = _Graph(pts)
        _graphs[lid] = g
    return g


class _CloudIdx:
    """★ v2.6.62：只做"最近邻查询"的轻量索引。

    `_Graph` 建的时候要算**邻接表**（每条线的点云上千个点，全建一遍要好几秒）。
    菜单里只是想问"这条线离官方中心线多远" ⇒ 只要网格索引就够了（O(n)）。
    """

    __slots__ = ("pts", "cell", "idx")

    def __init__(self, pts: Sequence[Sequence[float]], cell: float = CELL_IDX):
        self.pts = [(float(p[0]), float(p[1])) for p in pts]
        self.cell = float(cell)
        self.idx: Dict[Tuple[int, int], List[int]] = {}
        for i, (x, y) in enumerate(self.pts):
            self.idx.setdefault((int(x // self.cell), int(y // self.cell)), []).append(i)

    def nearest(self, x: float, y: float, max_r: float = DEV_MAX_R
                ) -> Optional[Tuple[int, float, float, float]]:
        if not self.pts:
            return None
        best = None
        bd = max_r * max_r
        gx, gy = int(x // self.cell), int(y // self.cell)
        for r in range(0, int(max_r // self.cell) + 2):
            if r > 0 and ((r - 1) * self.cell) ** 2 > bd:
                break
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if r > 0 and max(abs(dx), abs(dy)) != r:
                        continue
                    for i in self.idx.get((gx + dx, gy + dy), ()):
                        px, py = self.pts[i]
                        d2 = (px - x) ** 2 + (py - y) ** 2
                        if d2 < bd:
                            bd = d2
                            best = (i, px, py, math.sqrt(d2))
            if best is not None and r >= 1 and ((r - 1) * self.cell) ** 2 > bd:
                break
        return best


_cidxs: Dict[str, "_CloudIdx"] = {}


def _cidx(line_id: str) -> Optional[_CloudIdx]:
    lid = str(line_id)
    c = _cidxs.get(lid)
    if c is None:
        pts = cloud_of(lid)
        if not pts:
            return None
        c = _CloudIdx(pts)
        _cidxs[lid] = c
    return c


def _resample(pts: Sequence[Sequence[float]], step: float
              ) -> List[Tuple[float, float]]:
    """沿折线按固定步长取点（量"离底图多远"要的是**整条线**，不是只有顶点）。"""
    P = [(float(p[0]), float(p[1])) for p in pts]
    if len(P) < 2:
        return P
    out: List[Tuple[float, float]] = []
    for i in range(len(P) - 1):
        x0, y0 = P[i]
        x1, y1 = P[i + 1]
        L = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(math.ceil(L / step)))
        for k in range(n):
            t = k / n
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    out.append(P[-1])
    return out


def cloud_dev(line_id: str, pts: Sequence[Sequence[float]]) -> Optional[float]:
    """这条折线**离官方中心线**多远（p90，单位 = 原图像素 = 场景单位）。

    ★ 用的是官方点云（`trace_cloud.json` 就是从原图抽的中心线），不是我自己的画法。
    ★ 采样点在本线点云里**找不到**邻居（跑飞了）⇒ 记满分 DEV_MAX_R，
      这样"脱线"的画法不会被算成"很准"（曾经踩过：只统计找得到的点）。
    """
    c = _cidx(line_id)
    if c is None:
        return None
    sp = _resample(pts, DEV_SAMPLE)
    if not sp:
        return None
    ds: List[float] = []
    for x, y in sp:
        n = c.nearest(x, y, DEV_MAX_R)
        ds.append(n[3] if n is not None else DEV_MAX_R)
    ds.sort()
    return ds[min(len(ds) - 1, int(0.9 * (len(ds) - 1)))]


def deviation(line_id: str, x: float, y: float) -> Optional[float]:
    """这一站离本线官方走廊中心线多少像素。抽不到就给 None。"""
    g = _graph(line_id)
    if g is None:
        return None
    n = g.nearest(float(x), float(y))
    return None if n is None else n[3]


def snap(line_ids: Sequence[str], x: float, y: float,
         max_r: float = SNAP_MAX) -> Optional[Tuple[float, float, float]]:
    """把 (x, y) 吸到**这些线里最近的那条**官方走廊上。

    返回 (px, py, 吸了多少像素)；没有任何一条线够近就给 None（不硬拉）。
    换乘站同属多条线 ⇒ 取最近的那条，这跟"拖动时人眼盯的是哪条线"一致。
    """
    best = None
    for lid in line_ids or ():
        g = _graph(lid)
        if g is None:
            continue
        n = g.nearest(float(x), float(y), max_r)
        if n is None:
            continue
        if best is None or n[3] < best[2]:
            best = (n[1], n[2], n[3])
    return best


def trace(line_id: str, ax: float, ay: float, bx: float, by: float,
          max_r: float = SNAP_MAX) -> Optional[List[Tuple[float, float]]]:
    """沿官方走廊把 A→B 的中心线走出来（甲）。

    返回一串点（**不含 A、B 本身** —— 渲染器会自己把两端接上站点），
    走不通 / 端点离走廊太远就给 None（调用方保持原来的画法）。
    """
    raw = _path_raw(line_id, ax, ay, bx, by, max_r)
    if not raw:
        return None
    pts = _post(raw, RDP_EPS)
    return pts if len(pts) >= 2 else None


def _path_raw(line_id: str, ax: float, ay: float, bx: float, by: float,
              max_r: float = SNAP_MAX) -> Optional[List[Tuple[float, float]]]:
    """A* 走出来的**原始**路径（未简化）。`trace` / `trace_smooth` 共用。"""
    g = _graph(line_id)
    if g is None:
        return None
    na = g.nearest(float(ax), float(ay), max_r)
    nb = g.nearest(float(bx), float(by), max_r)
    if na is None or nb is None:
        return None
    ids = g.astar(na[0], nb[0])
    if not ids:
        return None
    pts = [g.pts[i] for i in ids]
    # 两端掐掉被站点图标盖住的一截，免得起手先往回勾。
    # ★ 掐的长度要**跟着段长缩**：相邻两站只隔 80px 时按 45px 掐两头，
    #   整条路径会被掐光（实测 1号线"香蜜湖→购物公园" 站距 80px 直接走不通）。
    span = math.hypot(float(bx) - float(ax), float(by) - float(ay))
    trim = min(TRIM_END, 0.28 * span)
    while len(pts) > 1 and math.hypot(pts[0][0] - ax, pts[0][1] - ay) < trim:
        pts.pop(0)
    while len(pts) > 1 and math.hypot(pts[-1][0] - bx, pts[-1][1] - by) < trim:
        pts.pop()
    return pts


def _post(pts: List[Tuple[float, float]], rdp_eps: float
          ) -> List[Tuple[float, float]]:
    """简化三件套（v2.6.61）：RDP → 删近共线 → 再来一次 RDP → 合并过近点。"""
    # ★ RDP 只是"按幅度"删点，锯齿还有一种形态 —— 三个点几乎在一条直线上、
    #   中间那个只偏了几像素（A* 走网格时每 8px 一个台阶）。这些点幅度小、
    #   RDP 删不掉，但画出来就是一节一节的波浪 ⇒ 再过三道。
    pts = _rdp(pts, rdp_eps)
    pts = _drop_collinear(pts, COLLINEAR_EPS)
    pts = _rdp(pts, rdp_eps)
    pts = _min_step(pts, MIN_STEP)
    return pts


def _bucket_median(pts: List[Tuple[float, float]],
                   step: float = BUCKET_STEP) -> List[Tuple[float, float]]:
    """按**沿路径的弧长**分桶，每桶取中位点 ⇒ 把中心线的左右摇摆平均掉。

    ★ 官方位图的拐弯是圆角 + 抗锯齿 ⇒ 中心线在圆角附近会来回摆（不是真拐点）。
      逐点抄下来就是一串小碎折。按弧长分桶取中位后，一个圆角只剩一个点。
    ★ 桶数跟着段长走（每 step 一桶，3~14 桶）：段短的不会只剩两个点，
      段长的也不会因为桶太多而保留噪声。
    """
    if len(pts) < 3:
        return list(pts)
    acc = [0.0]
    for i in range(1, len(pts)):
        acc.append(acc[-1] + math.hypot(pts[i][0] - pts[i - 1][0],
                                        pts[i][1] - pts[i - 1][1]))
    total = acc[-1]
    if total < 1e-6:
        return list(pts)
    nb = max(3, min(14, int(round(total / step))))
    out: List[Tuple[float, float]] = []
    for b in range(nb):
        lo = total * b / nb
        hi = total * (b + 1) / nb
        if b == nb - 1:
            sel = [p for p, a in zip(pts, acc) if a >= lo]
        else:
            sel = [p for p, a in zip(pts, acc) if lo <= a < hi]
        if not sel:
            continue
        xs = sorted(p[0] for p in sel)
        ys = sorted(p[1] for p in sel)
        m = len(sel) // 2
        mx = xs[m] if len(xs) % 2 else 0.5 * (xs[m - 1] + xs[m])
        my = ys[m] if len(ys) % 2 else 0.5 * (ys[m - 1] + ys[m])
        out.append((mx, my))
    if len(out) < 2:
        return list(pts)
    out[0] = pts[0]
    out[-1] = pts[-1]
    return out


def trace_smooth(line_id: str, ax: float, ay: float, bx: float, by: float,
                 max_r: float = SNAP_MAX) -> Optional[List[Tuple[float, float]]]:
    """★ v2.6.62「探测弧度」：沿官方点云走，再平滑一次（分桶取中位）。

    和 `trace()` 的区别：`trace` 是"逐点照抄中心线"（会把圆角抄成碎折），
    这个是"沿弧长分桶取中位"（一个圆角一个点）⇒ 画出来是干净的弧。
    返回的点列同样**不含 A、B 本身**（渲染器会接上站点）。
    """
    raw = _path_raw(line_id, ax, ay, bx, by, max_r)
    if not raw:
        return None
    pts = _bucket_median(raw)
    pts = _post(pts, SMOOTH_RDP)
    return pts if len(pts) >= 2 else None


def seg_report(line_id: str, ax: float, ay: float, bx: float, by: float,
               cur_pts: Optional[Sequence[Sequence[float]]] = None) -> Dict:
    """★ v2.6.62：这一段的"官方体检报告" —— 三种画法各离底图多远。

    返回 dict：
        dev_now / dev_line / dev_arc   三种画法的 p90（None = 量不出来）
        arc_pts                        「探测弧度」算出来的点列（量不出来 = None）
        advice                         "line" / "arc" / "keep"
    单位都是**原图像素 = 场景单位**，越小越贴底图。
    """
    span = math.hypot(float(bx) - float(ax), float(by) - float(ay))
    line_pts = [(float(ax), float(ay)), (float(bx), float(by))]
    cur = [(float(p[0]), float(p[1])) for p in cur_pts] if cur_pts else list(line_pts)
    arc_pts = trace_smooth(line_id, ax, ay, bx, by)

    def _dev(pts):
        # ★ 三种画法都要**带上两端的站点**再量（traced 里存的只是中间点，
        #   渲染时由渲染器接上 A、B）—— 不加的话"中间点少"的画法会被算得更准。
        return cloud_dev(line_id, [(float(ax), float(ay))]
                         + [tuple(p[:2]) for p in pts]
                         + [(float(bx), float(by))])

    r = {
        "dev_now": _dev(cur),
        "dev_line": _dev([]),
        "dev_arc": _dev(arc_pts) if arc_pts else None,
        "arc_pts": arc_pts,
        "span": span,
        "advice": "keep",
    }
    cand = [(r["dev_line"], "line"), (r["dev_arc"], "arc")]
    cand = [c for c in cand if c[0] is not None]
    if cand:
        best = min(cand, key=lambda c: c[0])
        now = r["dev_now"]
        # 只有当"换一种画法"确实更好（好 3px 以上，量纲内的噪声）才建议换
        r["advice"] = best[1] if (now is None or best[0] < now - 3.0) else "keep"
    return r


def _drop_collinear(pts: List[Tuple[float, float]], eps: float
                    ) -> List[Tuple[float, float]]:
    """删掉"三点几乎共线"的中间点（只留真拐点）。"""
    out = list(pts)
    changed = True
    while changed and len(out) > 2:
        changed = False
        for i in range(1, len(out) - 1):
            x0, y0 = out[i - 1]
            x1, y1 = out[i]
            x2, y2 = out[i + 1]
            dx, dy = x2 - x0, y2 - y0
            L = math.hypot(dx, dy)
            if L < 1e-9:
                del out[i]
                changed = True
                break
            d = abs(dy * (x1 - x0) - dx * (y1 - y0)) / L
            # 中间点必须真的落在两端**之间**（不是往回勾）
            t = ((x1 - x0) * dx + (y1 - y0) * dy) / (L * L)
            if d < eps and -0.2 < t < 1.2:
                del out[i]
                changed = True
                break
    return out


def _min_step(pts: List[Tuple[float, float]], min_d: float
              ) -> List[Tuple[float, float]]:
    """相邻点太近 ⇒ 合并（`_chk_transfer_pair` 判"折点扎堆"的线是 35px）。"""
    if len(pts) < 3:
        return list(pts)
    out = [pts[0]]
    for p in pts[1:-1]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= min_d:
            out.append(p)
    last = pts[-1]
    if math.hypot(last[0] - out[-1][0], last[1] - out[-1][1]) >= min_d:
        out.append(last)
    else:
        out[-1] = last
    return out


def _rdp(pts: List[Tuple[float, float]], eps: float
         ) -> List[Tuple[float, float]]:
    """Ramer–Douglas–Peucker：把点列简化掉，去掉原图像素噪声带来的碎抖。"""
    if len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        x1, y1 = pts[i]
        x2, y2 = pts[j]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        best_d, best_k = -1.0, -1
        for k in range(i + 1, j):
            px, py = pts[k]
            if L < 1e-9:
                d = math.hypot(px - x1, py - y1)
            else:
                d = abs(dy * (px - x1) - dx * (py - y1)) / L
            if d > best_d:
                best_d, best_k = d, k
        if best_d > eps and best_k > 0:
            keep[best_k] = True
            stack.append((i, best_k))
            stack.append((best_k, j))
    return [p for p, k in zip(pts, keep) if k]
