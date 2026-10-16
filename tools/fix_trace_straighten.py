# -*- coding: utf-8 -*-
"""把描线路径**拉直**：官方画的是直线的地方，就别画成波浪。

用户原话：「现在的线路是凹凸不平的，本该是直线的线路，使用自动描线、偏差检查等
并不能很好的绘制出来」。

原因：描线是贴着官方位图的**像素中心线**走出来的。位图有噪声、线宽不均 ⇒ 中心线
会左右摇摆（蛇形），RDP(18) 之后仍留下一串 20~40° 的小拐点 ⇒ 渲染出来就是波浪。
（实测：11号线 宝安→前海湾 一段描出 10 个点，平均 60px 一个拐点。）

做法（不动站点，只动 traced 里的那串点）：
  ① **官方判直线**：取该段走廊里的官方同色像素，做 PCA 主轴拟合，
     残差 p90 ≤ STRAIGHT_TOL ⇒ 官方这一段的的确确是直的 ⇒ 直接写 [A, B] 两点；
  ② 否则（官方真拐了）再**去抖动**：RDP(32) + 共线合并(12px) + 短边合并；
  ③ **自检**：拉直后这条路径离官方同色像素的 p90 若比原来差超过 3px ⇒ 不采用
     （宁可留着波浪，也不能把线拉离官方）。

用法：
    python tools/fix_trace_straighten.py            # 只看不动（打统计）
    python tools/fix_trace_straighten.py --apply    # 写入（先备份）
"""
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"

LINES_F = DATA / "lines.json"
ST_F = DATA / "stations.json"
doc = json.loads(LINES_F.read_text(encoding="utf-8"))
LINES = doc["lines"]
ST = json.loads(ST_F.read_text(encoding="utf-8"))["stations"]
COLORS = json.loads((ROOT / "_tmp_official_colors.json").read_text(encoding="utf-8"))
OFF = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)

TOL = 48
STRIP = 90.0         # 走廊带宽：只取离 AB ±90px 内的官方像素
STRAIGHT_TOL = 18.0  # 官方残差 p90 ≤ 它 ⇒ 判"官方这段是直的"
RDP_EPS = 14.0       # 去抖动的简化容差
COLLINEAR = 8.0     # 中间点离两端连线 ≤ 它 ⇒ 删掉这个点
MIN_EDGE = 42.0      # 保留的最短边（<35px 会触发"折点扎堆"的判据）
WORSE_OK = 3.0       # 拉直后离官方线的 p90 最多允许变差多少


def corridor_xy(st, lid):
    x, y = float(st.get("x", 0)), float(st.get("y", 0))
    for b in (st.get("alt_bodies") or []):
        if str(b.get("line") or "") == str(lid):
            try:
                x, y = float(b["x"]), float(b["y"])
            except (KeyError, TypeError, ValueError):
                break
    d = (st.get("lanes") or {}).get(str(lid))
    if d:
        try:
            x, y = x + float(d[0]), y + float(d[1])
        except (IndexError, TypeError, ValueError):
            pass
    return np.array([x, y])


def line_mask_points(rgb):
    d = np.abs(OFF - np.array(rgb, dtype=np.int16)).sum(axis=2)
    ys, xs = np.nonzero(d < TOL)
    return np.column_stack([xs, ys]).astype(float)


def corridor_pts(M, A, B):
    ab = B - A
    L = float(np.hypot(*ab))
    if L < 1e-6:
        return None
    u = ab / L
    v = np.array([-u[1], u[0]])
    rel = M - A
    t = rel @ u
    s = rel @ v
    m = (t > -40) & (t < L + 40) & (np.abs(s) < STRIP)
    if int(m.sum()) < 50:
        return None
    return M[m]


def residual_to_axis(P, c, n):
    return float(np.percentile(np.abs((P - c) @ n), 90))


def pca_axis(P):
    c = P.mean(axis=0)
    ev, evec = np.linalg.eigh(np.cov((P - c).T))
    main = evec[:, int(np.argmax(ev))]
    return c, main, np.array([-main[1], main[0]])


def rdp(P, eps):
    if len(P) < 3:
        return P
    keep = np.zeros(len(P), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(P) - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        a, b = P[i0], P[i1]
        ab = b - a
        L2 = float(ab @ ab)
        mid = P[i0 + 1:i1]
        if mid.size == 0:
            continue
        if L2 < 1e-9:
            d = np.linalg.norm(mid - a, axis=1)
        else:
            tt = np.clip(((mid - a) @ ab) / L2, 0, 1)
            d = np.linalg.norm(mid - (a + tt[:, None] * ab), axis=1)
        j = int(np.argmax(d)) + i0 + 1
        if d.max() > eps:
            keep[j] = True
            stack.append((i0, j))
            stack.append((j, i1))
    return P[keep]


def drop_collinear(P, tol=COLLINEAR):
    """删掉"三点几乎共线"的中间点 —— 像素中心线的蛇形主要就是这些点"""
    P = list(P)
    changed = True
    while changed and len(P) > 2:
        changed = False
        for i in range(1, len(P) - 1):
            a, b, c = np.array(P[i - 1], float), np.array(P[i], float), np.array(P[i + 1], float)
            ab = b - a
            ac = c - a
            L = float(np.hypot(*ac))
            if L < 1e-6:
                continue
            # 点 b 到 a→c 连线的距离
            d = abs(float(np.cross(ac, ab))) / L
            t = float(ab @ ac) / (L * L)
            if d < tol and -0.2 < t < 1.2:
                del P[i]
                changed = True
                break
    return np.array(P, float)


def merge_short(P, min_d=MIN_EDGE):
    if len(P) < 3:
        return P
    out = [P[0]]
    for p in P[1:-1]:
        if float(np.hypot(*(p - out[-1]))) >= min_d:
            out.append(p)
    last = P[-1]
    if float(np.hypot(*(last - out[-1]))) >= min_d:
        out.append(last)
    else:
        out[-1] = last
    return np.array(out, float)


def main():
    apply_ = "--apply" in sys.argv
    traced = doc.get("traced") or {}
    print("=" * 92)
    print("描线拉直：官方画的是直线的地方，就别画成波浪   %s"
          % ("**写入**" if apply_ else "只看不动"))
    print("=" * 92)
    cache = {}
    n_straight = n_simpl = n_keep = n_skip = 0
    dev_before, dev_after = [], []
    out = {}

    for l in LINES:
        lid = str(l.get("id"))
        cols = (COLORS.get(lid) or {}).get("colors") or []
        if not cols:
            continue
        rgb = cols[0][0]
        M = cache.get(lid)
        if M is None:
            M = line_mask_points(rgb)
            cache[lid] = M
            tc = cKDTree(M)
            cache[lid + "_tree"] = tc
        tc = cache[lid + "_tree"]
        if len(M) < 500:
            continue
        seq = [n for n in (l.get("stations") or []) if n in ST]
        for i in range(len(seq) - 1):
            a, b = seq[i], seq[i + 1]
            key = "%s|%s|%s" % (lid, a, b)
            tp = traced.get(key)
            if not tp or len(tp) < 3:
                continue
            A = corridor_xy(ST[a], lid)
            B = corridor_xy(ST[b], lid)
            P = corridor_pts(M, A, B)
            if P is None:
                n_skip += 1
                continue
            c, main, n = pca_axis(P)
            r90 = residual_to_axis(P, c, n)
            T = np.array(tp, float)
            old90 = residual_to_axis(T, c, n)          # 一致性用"同一根主轴"量
            d_old, _ = tc.query(T, k=1)
            old_dev = float(np.percentile(d_old, 90))
            if r90 <= STRAIGHT_TOL:
                Q = np.array([A, B], float)
                tag = "官方是直的"
            else:
                Q = merge_short(drop_collinear(rdp(T, RDP_EPS)))
                tag = "去抖动"
            d_new, _ = tc.query(Q, k=1)
            new_dev = float(np.percentile(d_new, 90))
            if new_dev > old_dev + WORSE_OK:
                n_keep += 1                              # 拉直后离官方太远 ⇒ 不采用
                continue
            if len(Q) == 2 and r90 <= STRAIGHT_TOL:
                n_straight += 1
            else:
                n_simpl += 1
            out[key] = [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in Q]
            dev_before.append(old_dev)
            dev_after.append(new_dev)

    print("官方判直线 ⇒ 拉成两点：%d 段" % n_straight)
    print("官方有弯 ⇒ 去掉抖动点：%d 段（%d → %d 点）"
          % (n_simpl, sum(len(traced[k]) for k in out if len(out[k]) > 2),
             sum(len(out[k]) for k in out if len(out[k]) > 2)))
    print("拉直后离官方太远、保持原样：%d 段" % n_keep)
    print("走廊像素不够、跳过：%d 段" % n_skip)
    if dev_before:
        print("离官方同色像素 p90：拉直前 %.1fpx → 拉直后 %.1fpx"
              % (float(np.mean(dev_before)), float(np.mean(dev_after))))
    print("总点数：%d → %d" % (sum(len(traced[k]) for k in traced),
                             sum(len(out.get(k, traced[k])) for k in traced)))
    if not apply_:
        print("（没写入。确认后加 --apply）")
        return 0
    bak = DATA / ("lines.json.bak_straight_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(LINES_F, bak)
    for k, Q in out.items():
        traced[k] = Q
    doc["traced"] = traced
    LINES_F.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[备份] %s" % bak.name)
    print("[写入] 改动 %d 段" % len(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
