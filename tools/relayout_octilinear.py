# -*- coding: utf-8 -*-
"""
relayout_octilinear.py —— 把 379 个站点的坐标**重画成官方示意图的样子**。

==========================================================================
用户原话
==========================================================================
「重构所有站点的排序（现在很乱，改为和官方图纸一样的显示顺序，
   间距可以变大，按照你认为适合观看的样子做）」

==========================================================================
"乱"到底是什么（用数字说话，不靠感觉）
==========================================================================
现在的 x/y 是当年从**位图上量**出来的（`tools/calibrate_coords.py`），
本质是"地理近似 + 测量噪声"。体检（`tools/_audit_pending.py`）实测：

    相邻站距  min 30.8 / max 981.4 / 均值 228.0
    **间距变异系数 CV = 0.606**     ← 同一条线内差 30 倍
    八向合规（段方向离 0/45/90 ≤5°）  248/441 = **56.2%**
    直线度（连续两段同向）            **66.5%**

后果：本来该是一条直线的十几站，因为 y 有 ±30px 的测量噪声，
渲染器的八向化（`ui/metro_render.py::octilinear_waypoints_tagged`）会在
每一站之间**插一个 45° 折角** —— 线看起来毛躁、歪扭，就是"乱"。

==========================================================================
改法：分段拟合 + 带锚最小二乘
==========================================================================
  ① **分段拟合**：把每条线切成若干"直线段"，每段统一给一个八向方向。
  ② **最小二乘**：p_b - p_a = ℓ·d （走向八向 + 段长统一）
                  ＋ λ·(p_i - 原坐标)   ← 锚
  ③ 用新坐标回到 ①，迭代 4 轮（越拉越干净）。

★★ 为什么"每段独立吸附八向"不行（第一版踩的坑，实测更差）：
   本来笔直的十几站，量出来的角度各自差几度，被吸成 (1,0)(1,1)(1,0)(1,1)…
   ⇒ 直线度 66% → **35%**，线变成锯齿。肉眼看就是"更乱了"。
   正解是先分段、再给**整段**一个方向。

★★ 为什么必须有锚 λ（第二版踩的坑）：
   原始坐标是真实几何 ⇒ 图里 63 个环**天然闭合**。
   一旦把段长强行统一，这些环在数学上就合不上了。没有锚时，
   最小二乘为了照顾"等间距"会把整张图拧变形 —— 实测
   CV 0.606→**0.895**、过近站对 11→**516**（站点大规模挤在一起）。
   锚把解拽回真实几何附近 ⇒ 走向拉直、间距拉匀，但位置不跑偏。

==========================================================================
用法（先出草稿看指标，确认没问题再落盘）
==========================================================================
    python tools/relayout_octilinear.py                    # 只算不写，打印指标
    python tools/relayout_octilinear.py --sweep            # 扫参数对比
    python tools/relayout_octilinear.py --out draft.json   # 存草稿
    python tools/relayout_octilinear.py --apply            # ★ 落盘（自动备份）
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STATIONS = ROOT / "data" / "stations.json"
LINES = ROOT / "data" / "lines.json"

# 非地铁系统（有轨电车 / 云巴）：站点密、里程短，跟地铁不是一个尺度。
NON_METRO = {"有轨电车", "有轨电车支线", "坪山云巴"}

# 渲染器八向化的容差（`ui/metro_render.py`）—— 复刻过来算"视觉毛刺数"
OCTI_TOL = 0.16        # 相对容差
OCTI_TOL_PX = 26.0     # 绝对容差（场景单位）


# ---------------------------------------------------------------- 基础几何

def snap_dir(dx: float, dy: float):
    """把向量吸附到最近的八向单位向量。"""
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return (1.0, 0.0)
    k = round(math.atan2(dy, dx) / (math.pi / 4.0))
    a = k * (math.pi / 4.0)
    return (math.cos(a), math.sin(a))


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ---------------------------------------------------------------- 载入

def load():
    st = json.load(open(STATIONS, encoding="utf-8"))["stations"]
    ln = json.load(open(LINES, encoding="utf-8"))["lines"]
    return st, ln


def build_edges(ln):
    """返回 [(线id, 站a, 站b), ...]，同一对站只留一次。"""
    seen = set()
    out = []
    for L in ln:
        a = L["stations"]
        for i in range(len(a) - 1):
            key = (a[i], a[i + 1]) if a[i] < a[i + 1] else (a[i + 1], a[i])
            if key in seen:
                continue
            seen.add(key)
            out.append((L["id"], a[i], a[i + 1]))
    return out


# ---------------------------------------------------------------- 直线段识别

OCTI_ANGLES = [k * (math.pi / 4.0) for k in range(8)]


def _ang_dev(a: float, b: float) -> float:
    """两个角度的最小夹角（弧度，0..π）。"""
    d = (a - b) % (2 * math.pi)
    if d > math.pi:
        d = 2 * math.pi - d
    return d


def segment_line(pts, penalty: float):
    """
    把一条线的站点序列切成若干**直线段**，每段统一给一个八向方向。

    ★★★ 这是整个重排最关键的一步。用动态规划做分段拟合：
        总代价 = Σ(段内各边与该段八向方向的偏角²) + 每多一段罚 penalty
    penalty 越大 ⇒ 段越少越长 ⇒ 线越"直"、越像官方图。

    返回 [(起始边下标, 结束边下标, (ux, uy)), ...]
    """
    m = len(pts) - 1
    if m <= 0:
        return []
    ang = []
    for i in range(m):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        ang.append(math.atan2(dy, dx) if (dx or dy) else 0.0)

    # seg_cost[i][j] = 边 i..j（含）共用同一个八向方向时的最小偏角平方和
    seg_cost = [[0.0] * m for _ in range(m)]
    seg_dir = [[0] * m for _ in range(m)]
    for i in range(m):
        acc = [0.0] * 8
        for j in range(i, m):
            a = ang[j]
            for k, th in enumerate(OCTI_ANGLES):
                acc[k] += _ang_dev(a, th) ** 2
            best = min(range(8), key=lambda k: acc[k])
            seg_cost[i][j] = acc[best]
            seg_dir[i][j] = best

    INF = float("inf")
    best = [INF] * (m + 1)
    prev = [-1] * (m + 1)
    best[0] = -penalty          # 第一段不罚
    for j in range(1, m + 1):
        for i in range(j):
            c = best[i] + seg_cost[i][j - 1] + penalty
            if c < best[j]:
                best[j] = c
                prev[j] = i

    out = []
    j = m
    while j > 0:
        i = prev[j]
        th = seg_dir[i][j - 1] * (math.pi / 4.0)
        out.append((i, j - 1, (math.cos(th), math.sin(th))))
        j = i
    out.reverse()

    # 相邻段方向相同就合并（DP 里合并其实更优，但回溯不会产生）
    merged = []
    for s in out:
        if merged and abs(merged[-1][2][0] - s[2][0]) < 1e-9 \
                and abs(merged[-1][2][1] - s[2][1]) < 1e-9:
            merged[-1] = (merged[-1][0], s[1], s[2])
        else:
            merged.append(s)
    return merged


# ---------------------------------------------------------------- 核心

def relayout(st, ln, L_metro: float, tram_scale: float = 1.0,
             iters: int = 4, anchor: float = 1.0, penalty: float = 0.06,
             length_mode: str = "perline", w_perp: float = 8.0,
             w_par: float = 1.0, dmin: float = 0.0, repel: int = 1,
             w_sep: float = 6.0, w_clamp: float = 25.0,
             lmin_f: float = 0.45, lmax_f: float = 2.0, verbose: bool = False):
    """
    返回 新坐标 {站名: (x, y)}。

    L_metro      地铁统一站距（length_mode='uniform' 时用）
    tram_scale   非地铁系统相对自身平均站距的放大倍数
    anchor       λ：向原始位置的回拉权重（**能不能收敛的关键**）
    penalty      每多一段直线段的罚分（越大越"直"）
    length_mode  'perline' = 每条线用自己原本的平均站距（保各自尺度）
                 'uniform' = 全部用 L_metro（全网统一间距）
    """
    import numpy as np

    names = list(st.keys())
    nidx = {n: i for i, n in enumerate(names)}
    N = len(names)

    seed0 = {n: (float(st[n]["x"]), float(st[n]["y"])) for n in names}
    cx = sum(p[0] for p in seed0.values()) / N
    cy = sum(p[1] for p in seed0.values()) / N
    seed = {n: (p[0] - cx, p[1] - cy) for n, p in seed0.items()}

    line_step = {}
    for L in ln:
        ss = [seed[s] for s in L["stations"]]
        if len(ss) < 2:
            line_step[L["id"]] = L_metro
            continue
        m = sum(dist(ss[i], ss[i + 1]) for i in range(len(ss) - 1)) / (len(ss) - 1)
        if L["id"] in NON_METRO:
            line_step[L["id"]] = m * tram_scale
        else:
            line_step[L["id"]] = (L_metro if length_mode == "uniform" else m)

    edges = build_edges(ln)
    E = len(edges)

    edges = build_edges(ln)
    E = len(edges)

    # 邻接表（斥力时"直接相邻的两站"不该被推开 —— 它们本来就该挨着）
    adj = set()
    for lid, a, b_ in edges:
        adj.add((a, b_))
        adj.add((b_, a))

    p = dict(seed)
    for it in range(iters):
        # ① 逐线分段 → 每条边的八向目标方向
        dirs = {}
        for L in ln:
            ss = L["stations"]
            pts = [p[s] for s in ss]
            for (i0, i1, d) in segment_line(pts, penalty):
                for e in range(i0, i1 + 1):
                    dirs[(L["id"], ss[e], ss[e + 1])] = d

        # ② 最小二乘（**各向异性加权**，这一步是整个算法的胜负手）
        #
        #    残差 r = (p_b - p_a) - ℓ·d  拆成两个方向分别罚：
        #      · 垂直分量  r·n  → 权重 w_perp（**重罚**）
        #      · 沿线分量  r·d  → 权重 w_par （轻罚）
        #
        #    ★★★ 为什么必须分开罚（第三版才想明白）：
        #      环合不上是**数学上必然**的（63 个独立环），所以一定有残差。
        #      各向同性最小二乘会把残差平均摊到两个方向 ⇒
        #      垂直方向的残差让线**弯**（这正是"乱"的观感），
        #      而沿线方向的残差只是"这一站离上一站远一点"，肉眼根本看不出。
        #    ★★ 实现坑：投影 d·Δp **混合了 x 和 y**，而"A 共享 + B 两列"的写法
        #      每一行只能表达"同一套系数分别作用在 x 和 y 上"（= 分量约束）。
        #      拿它去写投影，写出来的其实是"x 分量 = ℓ·d0、y 分量 = ℓ·d1"
        #      以外的怪东西 —— 实测宽高比被拉成 4.15、八向合规掉到 20%。
        #      正解：把未知数扩成 **2N 维**（x 全在前面、y 全在后面），
        #      每行就能混着写 x/y 系数了。
        # ②a 每条边的**沿线权重自适应**：
        #    偏离目标越长/越短，权重越大 ⇒ 把"特别长的段"和"特别短的段"
        #    往中间拽。固定权重时实测 min 13 / max 828（均值 221），
        #    两端各有一撮极端值把 CV 撑到 0.45。
        w_par_e = {}
        for (lid, a, b_) in edges:
            tgt = line_step[lid]
            cur = dist(p[a], p[b_])
            if tgt <= 1e-9 or cur <= 1e-9:
                w_par_e[(lid, a, b_)] = w_par
                continue
            ratio = cur / tgt
            over = max(ratio, 1.0 / ratio)          # 偏离倍数（≥1）
            w_par_e[(lid, a, b_)] = min(w_par * (over ** 2), w_par * 60.0)

        # ②b 分离约束：把"这两站必须至少分开 dmin"写成**线性行**。
        #    ★★ 为什么不再用事后硬推（斥力）：
        #      斥力把站点推离它该在的直线，下一轮最小二乘又把它拉回来 ——
        #      两个目标轮流打架，实测最后一轮不推 ⇒ 过近对回到 30+、非邻最小 1.2；
        #      最后一轮推 ⇒ 毛刺从 43 涨到 66、八向掉到 81%。怎么排都救不回来。
        #    ★ 正解：沿"当前这两站的连线方向 u"要求 u·(p_c - p_a) = dmin。
        #      u 每轮重算（线性化），于是它**跟八向、跟段长一起**被最小二乘
        #      统一权衡 —— 谁该让一点由求解器决定，而不是我先推再被拉回去。
        seps = []
        if dmin > 0:
            lst = list(names)
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    a, c = lst[i], lst[j]
                    if (a, c) in adj:
                        continue
                    dx = p[c][0] - p[a][0]
                    dy = p[c][1] - p[a][1]
                    d = math.hypot(dx, dy)
                    if d < dmin:
                        if d < 1e-6:
                            dx, dy, d = 1.0, 0.0, 1e-6
                        seps.append((a, c, dx / d, dy / d))
        V = len(seps)

        # ②c 段长上下限（硬约束行）：
        #    段长一旦被压到接近 0，"下一站"就跑到"上一站"后面去了 ⇒
        #    线上出现**折返**（改前 17 处，不带这行会变成 33~77 处，肉眼就是断头路）。
        #    同理，特别长的段会把 CV 撑大。两端各钉一个上下限。
        clamps = []
        for (lid, a, b_) in edges:
            d = dirs.get((lid, a, b_))
            if d is None:
                continue
            tgt = line_step[lid]
            proj = (p[b_][0] - p[a][0]) * d[0] + (p[b_][1] - p[a][1]) * d[1]
            lo, hi = lmin_f * tgt, lmax_f * tgt
            if proj < lo:
                clamps.append((a, b_, d[0], d[1], lo))
            elif proj > hi:
                clamps.append((a, b_, d[0], d[1], hi))
        C = len(clamps)

        R = 2 * E + 2 * N + V + C
        A = np.zeros((R, 2 * N))
        b = np.zeros(R)
        for r, (lid, a, b_) in enumerate(edges):
            d = dirs.get((lid, a, b_))
            if d is None:
                d = snap_dir(p[b_][0] - p[a][0], p[b_][1] - p[a][1])
            nx, ny = -d[1], d[0]           # 垂直于该段八向方向的单位向量
            ia, ib = nidx[a], nidx[b_]
            wpe = w_par_e[(lid, a, b_)]
            # 垂直（重罚）：n0·Δx + n1·Δy = 0
            A[2 * r, ia] = -w_perp * nx
            A[2 * r, ib] = w_perp * nx
            A[2 * r, N + ia] = -w_perp * ny
            A[2 * r, N + ib] = w_perp * ny
            # 沿线（自适应）：d0·Δx + d1·Δy = ℓ
            A[2 * r + 1, ia] = -wpe * d[0]
            A[2 * r + 1, ib] = wpe * d[0]
            A[2 * r + 1, N + ia] = -wpe * d[1]
            A[2 * r + 1, N + ib] = wpe * d[1]
            b[2 * r + 1] = wpe * line_step[lid]
        # 锚：拽回**上一轮的位置**（不是原始噪声坐标）—— 每轮都更干净一点
        wa = math.sqrt(max(anchor, 1e-9))
        anc = p if it > 0 else seed
        for n in names:
            i = nidx[n]
            A[2 * E + 2 * i, i] = wa
            b[2 * E + 2 * i] = wa * anc[n][0]
            A[2 * E + 2 * i + 1, N + i] = wa
            b[2 * E + 2 * i + 1] = wa * anc[n][1]
        # 分离行
        for v, (a, c, ux, uy) in enumerate(seps):
            row = 2 * E + 2 * N + v
            ia, ic = nidx[a], nidx[c]
            A[row, ia] = -w_sep * ux
            A[row, ic] = w_sep * ux
            A[row, N + ia] = -w_sep * uy
            A[row, N + ic] = w_sep * uy
            b[row] = w_sep * dmin
        # 段长上下限行
        for v, (a, c_, dx, dy, tgt) in enumerate(clamps):
            row = 2 * E + 2 * N + V + v
            ia, ic = nidx[a], nidx[c_]
            A[row, ia] = -w_clamp * dx
            A[row, ic] = w_clamp * dx
            A[row, N + ia] = -w_clamp * dy
            A[row, N + ic] = w_clamp * dy
            b[row] = w_clamp * tgt

        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        p = {n: (float(sol[nidx[n]]), float(sol[N + nidx[n]])) for n in names}

        # ③ 斥力：把挤在一起的非邻站推开（八向化会让某些站几乎重叠，
        #    实测非邻站最小间距一度掉到 **1.4** 个场景单位 = 两个圆点叠在一起）
        #    ★ 最后一轮**不推**：推挤会把站点拽离它该在的直线 ⇒
        #      实测毛刺从 43 涨到 66。让最后一轮以"拉直"收尾，
        #      推挤的效果由下一轮的锚继承，两者就兼得了。
        if dmin > 0 and it < iters - 1:
            lst = list(names)
            for _k in range(repel):
                for i in range(len(lst)):
                    for j in range(i + 1, len(lst)):
                        a, c = lst[i], lst[j]
                        if (a, c) in adj:
                            continue
                        dx = p[c][0] - p[a][0]
                        dy = p[c][1] - p[a][1]
                        d = math.hypot(dx, dy)
                        if d >= dmin:
                            continue
                        if d < 1e-6:
                            dx, dy, d = 1.0, 0.0, 1e-6
                        push = (dmin - d) * 0.5
                        ux, uy = dx / d, dy / d
                        p[a] = (p[a][0] - ux * push, p[a][1] - uy * push)
                        p[c] = (p[c][0] + ux * push, p[c][1] + uy * push)

        if verbose:
            nseg = sum(len(segment_line([p[s] for s in L["stations"]], penalty))
                       for L in ln)
            print(f"    iter {it}: 直线段合计 {nseg} 条")

    return {n: (p[n][0] + cx, p[n][1] + cy) for n in names}


# ---------------------------------------------------------------- 指标

def metrics(st_new, ln, edges):
    """一套**可复核**的指标。改前改后各跑一次就能看出有没有真变好。"""
    lens_all, lens_by_line = [], {}
    for lid, a, b in edges:
        d = dist(st_new[a], st_new[b])
        lens_all.append(d)
        lens_by_line.setdefault(lid, []).append(d)

    mean = sum(lens_all) / len(lens_all)
    cv = (sum((d - mean) ** 2 for d in lens_all) / len(lens_all)) ** 0.5 / mean

    inner = []
    for lid, ds in lens_by_line.items():
        if len(ds) < 2:
            continue
        m = sum(ds) / len(ds)
        inner.append((sum((d - m) ** 2 for d in ds) / len(ds)) ** 0.5 / m)

    ok5 = ok2 = 0
    for lid, a, b in edges:
        dx = st_new[b][0] - st_new[a][0]
        dy = st_new[b][1] - st_new[a][1]
        if dist(st_new[a], st_new[b]) < 1e-9:
            continue
        ang = math.degrees(math.atan2(dy, dx)) % 90.0
        dev = min(ang, abs(ang - 45.0), abs(ang - 90.0))
        if dev <= 5.0:
            ok5 += 1
        if dev <= 2.0:
            ok2 += 1

    # 视觉毛刺：完全复刻 ui/metro_render.py::octilinear_waypoints_tagged 的判断
    jog = 0
    for L in ln:
        ss = L["stations"]
        for i in range(len(ss) - 1):
            a, b = st_new[ss[i]], st_new[ss[i + 1]]
            dx, dy = b[0] - a[0], b[1] - a[1]
            adx, ady = abs(dx), abs(dy)
            big = max(adx, ady)
            if big < 1e-6 or adx < 1e-6 or ady < 1e-6:
                continue
            if min(adx, ady) < OCTI_TOL_PX:
                continue
            if abs(adx - ady) <= big * OCTI_TOL:
                continue
            jog += 1

    same = tot = 0
    for L in ln:
        ss = L["stations"]
        for i in range(len(ss) - 2):
            a, b, c = st_new[ss[i]], st_new[ss[i + 1]], st_new[ss[i + 2]]
            d1 = snap_dir(b[0] - a[0], b[1] - a[1])
            d2 = snap_dir(c[0] - b[0], c[1] - b[1])
            tot += 1
            if abs(d1[0] - d2[0]) < 1e-6 and abs(d1[1] - d2[1]) < 1e-6:
                same += 1

    names = list(st_new.keys())
    adj = set()
    for lid, a, b in edges:
        adj.add((a, b))
        adj.add((b, a))
    mind = float("inf")
    close = 0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if (a, b) in adj:
                continue
            d = dist(st_new[a], st_new[b])
            mind = min(mind, d)
            if d < 0.45 * mean:
                close += 1

    xs = [v[0] for v in st_new.values()]
    ys = [v[1] for v in st_new.values()]
    w, h = max(xs) - min(xs), max(ys) - min(ys)

    return {
        "间距均值": mean, "间距CV": cv,
        "线内CV": sum(inner) / len(inner) if inner else 0,
        "最小站距": min(lens_all), "最大站距": max(lens_all),
        "八向5": ok5 / len(edges), "八向2": ok2 / len(edges),
        "毛刺": jog, "毛刺率": jog / len(edges),
        "直线度": same / tot if tot else 0,
        "非邻最小": mind, "过近对": close,
        "宽": w, "高": h, "宽高比": w / h if h else 0,
    }


def show(tag, m, nedges):
    print(f"\n--- {tag} ---")
    print(f"  站距    均值 {m['间距均值']:7.1f}  CV {m['间距CV']:.3f}  线内CV {m['线内CV']:.3f}"
          f"   min {m['最小站距']:.1f} / max {m['最大站距']:.1f}")
    print(f"  八向合规 ≤5° {m['八向5']*100:5.1f}%    ≤2° {m['八向2']*100:5.1f}%")
    print(f"  视觉毛刺 {m['毛刺']}/{nedges} 段（{m['毛刺率']*100:.1f}%）  ← 渲染器要插 45° 折角的段，越低越干净")
    print(f"  直线度   {m['直线度']*100:5.1f}%   （连续两段同向的比例）")
    print(f"  重叠风险 非邻站最小间距 {m['非邻最小']:.1f}   过近站对 {m['过近对']}")
    print(f"  包围盒   {m['宽']:.0f} × {m['高']:.0f}   宽高比 {m['宽高比']:.2f}")


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--L", type=float, default=None, help="地铁统一站距")
    ap.add_argument("--tram-scale", type=float, default=1.0)
    ap.add_argument("--iters", type=int, default=10)
    ap.add_argument("--anchor", type=float, default=0.35)
    ap.add_argument("--penalty", type=float, default=0.3)
    ap.add_argument("--length-mode", default="perline", choices=["perline", "uniform"])
    ap.add_argument("--w-perp", type=float, default=8.0)
    ap.add_argument("--w-sep", type=float, default=10.0)
    ap.add_argument("--w-clamp", type=float, default=60.0)
    ap.add_argument("--dmin", type=float, default=0.6,
                    help="非邻站最小间距（× 平均站距）")
    ap.add_argument("--lmin-f", type=float, default=0.6,
                    help="段长下限（× 该线目标站距）")
    ap.add_argument("--lmax-f", type=float, default=2.0,
                    help="段长上限（× 该线目标站距）")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    st, ln = load()
    edges = build_edges(ln)
    old = {n: (v["x"], v["y"]) for n, v in st.items()}
    base_L = args.L or (sum(dist(old[a], old[b]) for _, a, b in edges) / len(edges))

    print(f"边（相邻站对）数 = {len(edges)}    站数 = {len(st)}    基准站距 L = {base_L:.1f}")
    m_old = metrics(old, ln, edges)
    show("改前（现状）", m_old, len(edges))

    if args.sweep:
        print("\n" + "=" * 92)
        print(f"{'mode':<8}{'penalty':>8}{'anchor':>8} | {'CV':>6}{'线内CV':>7}"
              f"{'八向5°':>8}{'毛刺':>6}{'直线度':>8}{'过近对':>7}{'宽高比':>7}")
        print("-" * 92)
        for mode in ("perline", "uniform"):
            for pen in (0.02, 0.06, 0.15, 0.40):
                for anc in (0.25, 0.5, 1.0, 2.0):
                    new = relayout(st, ln, base_L, args.tram_scale,
                                   iters=args.iters, anchor=anc,
                                   penalty=pen, length_mode=mode)
                    m = metrics(new, ln, edges)
                    print(f"{mode:<8}{pen:>8}{anc:>8} | {m['间距CV']:>6.3f}{m['线内CV']:>7.3f}"
                          f"{m['八向5']*100:>7.1f}%{m['毛刺']:>6}{m['直线度']*100:>7.1f}%"
                          f"{m['过近对']:>7}{m['宽高比']:>7.2f}")
        return

    new = relayout(st, ln, base_L, args.tram_scale, iters=args.iters,
                   anchor=args.anchor, penalty=args.penalty,
                   length_mode=args.length_mode, w_perp=args.w_perp,
                   w_par=1.0, dmin=args.dmin * base_L, w_sep=args.w_sep,
                   w_clamp=args.w_clamp, lmin_f=args.lmin_f,
                   lmax_f=args.lmax_f, verbose=True)
    show("改后", metrics(new, ln, edges), len(edges))
    mv = sorted(dist(new[n], old[n]) for n in old)
    print(f"  位移      中位 {mv[len(mv)//2]:.0f}   最大 {mv[-1]:.0f}"
          f"   （整图跨度约 {m_old['宽']:.0f}）")

    if args.out:
        Path(args.out).write_text(
            json.dumps({n: {"x": round(v[0], 2), "y": round(v[1], 2)}
                        for n, v in new.items()}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"\n[OK] 草稿 → {args.out}")

    if args.apply:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = STATIONS.with_suffix(f".json.bak_relayout_{ts}")
        shutil.copy2(STATIONS, bak)
        data = json.load(open(STATIONS, encoding="utf-8"))
        nch = 0
        for n, v in data["stations"].items():
            if n in new:
                v["x"] = round(new[n][0], 2)
                v["y"] = round(new[n][1], 2)
                nch += 1
        json.dump(data, open(STATIONS, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n[OK] 落盘 {nch} 站 → {STATIONS}\n[OK] 备份 → {bak}")


if __name__ == "__main__":
    main()
