# -*- coding: utf-8 -*-
"""诊断：每一段**官方自己是不是直的**？我的描线相对那条直线歪了多少？

用户原话：「现在的线路是凹凸不平的，本该是直线的线路」。
描线是贴着官方位图的像素中心线走的 —— 位图有噪声、线宽不均 ⇒ 中心线会左右
摇摆（蛇形），RDP 之后仍留下一串 20~40° 的小拐点 ⇒ 渲染出来就是波浪。

判据（只认官方像素，不认我自己的画法）：
  对每一段，取官方同色像素里"投影落在这一段的 A→B 之间、且离 AB 不太远"的那些点，
  做 PCA 主轴拟合 ⇒ 官方这条线的**直线残差** p90。
  · 残差小（≤ STRAIGHT_TOL）⇒ 官方这一段的的确确是直线 ⇒ 就该直连；
  · 残差大 ⇒ 官方真的拐了（L 形/斜线），保留描线。

用法：
    python tools/_diag_seg_straightness.py            # 全部线
    python tools/_diag_seg_straightness.py 11 7       # 只看这几条
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT.parent / "软件" / "data"

LINES = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))["lines"]
ST = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
COLORS = json.loads((ROOT / "_tmp_official_colors.json").read_text(encoding="utf-8"))
OFF = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)

TOL = 48
STRIP = 90.0        # 只取离 AB 这条线 ±90px 范围内的官方像素（避免带上并行/交叉的线）
STRAIGHT_TOL = 16.0  # 官方直线残差 p90 小于这个 ⇒ 判"官方这段是直的"


def corridor_points(rgb, A, B):
    """这一段走廊里官方同色像素（投影落在 A→B 之间、离 AB ≤ STRIP）"""
    d = np.abs(OFF - np.array(rgb, dtype=np.int16)).sum(axis=2)
    ys, xs = np.nonzero(d < TOL)
    if len(xs) < 50:
        return None
    P = np.column_stack([xs, ys]).astype(float)
    ab = B - A
    L = float(np.hypot(*ab))
    if L < 1e-6:
        return None
    u = ab / L
    v = np.array([-u[1], u[0]])
    rel = P - A
    t = rel @ u
    s = rel @ v
    m = (t > -40) & (t < L + 40) & (np.abs(s) < STRIP)
    if m.sum() < 50:
        return None
    return P[m]


def pca_residual(P):
    """点到 PCA 主轴的距离（p90 / 最大）"""
    c = P.mean(axis=0)
    Q = P - c
    ev, evec = np.linalg.eigh(np.cov(Q.T))
    main = evec[:, int(np.argmax(ev))]
    n = np.array([-main[1], main[0]])
    d = np.abs(Q @ n)
    return float(np.percentile(d, 90)), float(d.max()), c, main


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("-")]
    doc = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))
    traced = doc.get("traced") or {}
    print("=" * 92)
    print("每一段：官方自己直不直？（残差 = 官方像素到 PCA 主轴的距离 p90）")
    print("  官方直 残差≤%.0fpx ⇒ 该直连；描线点歪 = 我的路径点离那条主轴多远" % STRAIGHT_TOL)
    print("=" * 92)
    rows = []
    for l in LINES:
        lid = str(l.get("id"))
        if want and lid not in want:
            continue
        cols = (COLORS.get(lid) or {}).get("colors") or []
        if not cols:
            continue
        rgb = cols[0][0]
        seq = [n for n in (l.get("stations") or []) if n in ST]
        for i in range(len(seq) - 1):
            a, b = seq[i], seq[i + 1]
            sa, sb = ST[a], ST[b]
            A = np.array([float(sa["x"]), float(sa["y"])])
            B = np.array([float(sb["x"]), float(sb["y"])])
            key = "%s|%s|%s" % (lid, a, b)
            tp = traced.get(key)
            P = corridor_points(rgb, A, B)
            if P is None:
                continue
            r90, rmx, c, main = pca_residual(P)
            dev = 0.0
            if tp and len(tp) > 2:
                T = np.array(tp, float)
                n = np.array([-main[1], main[0]])
                dev = float(np.percentile(np.abs((T - c) @ n), 90))
            rows.append((lid, a, b, r90, dev, len(tp or []), key in traced))
    rows.sort(key=lambda r: -r[4])
    print("%-4s %-8s %-8s | %-9s | %-9s | %s" % ("线", "从", "到", "官方残差", "描线点歪", "点数"))
    print("-" * 92)
    nstr = sum(1 for r in rows if r[3] <= STRAIGHT_TOL)
    print("官方判为直线的段：%d / %d（%.0f%%）" % (nstr, len(rows), 100.0 * nstr / max(1, len(rows))))
    print("-" * 92)
    for r in rows[:30]:
        tag = "★官方是直的却描出了拐点" if (r[3] <= STRAIGHT_TOL and r[5] > 2) else ""
        print("%-4s %-8s %-8s | %9.1f | %9.1f | %2d  %s"
              % (r[0], r[1][:6], r[2][:6], r[3], r[4], r[5], tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
