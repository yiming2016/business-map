# -*- coding: utf-8 -*-
"""诊断：当前站点坐标 vs 官方原图走廊，差在哪、差多少。

只读，不改任何数据。回答三个问题：
  Q1 站点贴在官方走廊上吗？（站点 → 该线点云 的最近距离）
  Q2 段方向是官方那种横/竖/45° 吗？（八向合规率）
  Q3 站距是官方那种均匀的吗？（段长变异系数 CV）

用法：
    python tools/_diag_vs_official.py
"""
import json
import math
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent.parent.parent / "软件" / "data"

st = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
ln = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))["lines"]
cloud = json.loads((DATA / "trace_cloud.json").read_text(encoding="utf-8"))


def octi(ang):
    """方向角离最近的 0/45/90/135... 差多少度"""
    a = abs(ang) % 90.0
    return min(a, 90.0 - a)


def line_stats(name, order, pts):
    """order=站名列表, pts=该线走廊点云(N,2)"""
    pos = [(st[s]["x"], st[s]["y"]) for s in order if s in st and st[s].get("x") is not None]
    out = {"name": name, "n": len(pos)}
    if len(pos) < 2 or len(pts) == 0:
        return out

    P = np.asarray(pos, dtype=float)
    C = np.asarray(pts, dtype=float)

    # Q1 每个站到走廊的最近距离
    d = np.sqrt(((P[:, None, :] - C[None, :, :]) ** 2).sum(-1)).min(axis=1)
    out["med"] = float(np.median(d))
    out["p90"] = float(np.percentile(d, 90))
    out["mx"] = float(d.max())
    out["worst"] = order[int(d.argmax())] if len(order) == len(P) else "?"

    # Q2 段方向八向合规（离 0/45/90 ≤5°）
    V = np.diff(P, axis=0)
    L = np.hypot(V[:, 0], V[:, 1])
    L[L < 1e-6] = 1e-6
    ang = np.degrees(np.arctan2(V[:, 1], V[:, 0]))
    dev = np.array([octi(a) for a in ang])
    out["octi"] = float((dev <= 5.0).mean())
    out["jog"] = int((dev > 5.0).sum())          # 渲染器要插 45° 折角的段
    out["nseg"] = len(L)

    # Q3 站距均匀度
    out["cv"] = float(L.std() / L.mean()) if L.mean() > 0 else 0.0
    out["ratio"] = float(L.max() / L.mean()) if L.mean() > 0 else 0.0
    out["avg"] = float(L.mean())
    return out


def official_octi(pts, radius=80):
    """官方走廊点云**自身**的走向有多八向（局部 PCA 主方向）。

    这一项是"标准答案"：如果官方走廊本身就只有 50% 八向 ⇒ 问题在描线(trace_cloud)，
    站点再怎么摆也摆不正；如果官方走廊有 85%+ ⇒ 走廊是准的，问题在站点没贴住。
    """
    from scipy.spatial import cKDTree
    C = np.asarray(pts, dtype=float)
    if len(C) < 200:
        return float("nan"), 0
    tree = cKDTree(C)
    rng = np.random.default_rng(0)
    idx = rng.choice(len(C), size=min(2500, len(C)), replace=False)
    devs = []
    for i in idx:
        nb = tree.query_ball_point(C[i], radius)
        if len(nb) < 40:
            continue
        Q = C[nb] - C[nb].mean(axis=0)
        ev = np.linalg.eigh(np.cov(Q.T))[1][:, -1]
        a = math.degrees(math.atan2(ev[1], ev[0]))
        devs.append(octi(a))
    if not devs:
        return float("nan"), 0
    d = np.array(devs)
    return float((d <= 5.0).mean()), len(d)


rows = []
for l in ln:
    name = l.get("name") or l.get("id") or "?"
    lid = str(l.get("id", name))
    order = l.get("stations") or []
    pts = cloud.get(lid) or []
    r = line_stats(lid, order, pts)
    r["o_octi"] = official_octi(pts)[0] if pts else float("nan")
    rows.append(r)

rows = [r for r in rows if r.get("nseg")]

print("=" * 92)
print("坐标抽样：站点 x/y 范围   min=%.0f  max=%.0f  （官方图是 0~8000）"
      % (min(v["x"] for v in st.values() if v.get("x") is not None),
         max(v["x"] for v in st.values() if v.get("x") is not None)))
print("=" * 92)
print("%-4s %4s | %-22s | %-20s | %-14s" % ("线", "站数", "① 离官方走廊(px)", "② 八向合规", "③ 站距均匀"))
print("%-4s %4s | %6s %6s %6s | %7s %6s | %6s %6s"
      % ("", "", "中位", "P90", "最差", "合规%", "毛刺", "CV", "最长/均"))
print("-" * 92)

rows_sorted = sorted(rows, key=lambda r: -r["p90"])
for r in rows_sorted:
    print("%-4s %4d | %6.1f %6.1f %6.1f | %6.0f%% %6d | %6.3f %6.2f   ← 最差站 %s"
          % (r["name"], r["n"], r["med"], r["p90"], r["mx"],
             r["octi"] * 100, r["jog"], r["cv"], r["ratio"], r.get("worst", "")))

print()
print("%-4s | %s" % ("线", "★ 官方走廊点云**自身**的八向合规（对照基准）"))
print("-" * 92)
for r in rows_sorted:
    v = r.get("o_octi", float("nan"))
    bar = "█" * int(round((v if v == v else 0) * 40))
    print("%-4s | %5.0f%%  %s" % (r["name"], (v if v == v else 0) * 100, bar))
oo = [r["o_octi"] for r in rows if r.get("o_octi") == r.get("o_octi")]
print("-" * 92)
print("官方走廊自身八向合规：中位 %.0f%%  （这是我该达到的天花板；站点合规 %.0f%%）"
      % (np.median(oo) * 100, np.mean([r["octi"] for r in rows]) * 100))

print("-" * 92)
allmed = np.median([r["med"] for r in rows])
allp90 = np.median([r["p90"] for r in rows])
allo = np.mean([r["octi"] for r in rows])
allj = sum(r["jog"] for r in rows)
alln = sum(r["nseg"] for r in rows)
allcv = np.mean([r["cv"] for r in rows])
print("全图：离走廊 中位 %.1fpx / P90 %.1fpx ｜ 八向合规 %.0f%% ｜ 毛刺 %d/%d 段 (%.0f%%) ｜ 站距 CV %.3f"
      % (allmed, allp90, allo * 100, allj, alln, allj / alln * 100, allcv))
print()
print("判读：官方图线宽约 30px ⇒ 站点贴走廊应 <20px；八向合规应 ≥85%；毛刺应 ≤12%；CV 应 ≤0.35")
