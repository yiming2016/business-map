# -*- coding: utf-8 -*-
"""诊断：**线路走向**和官方原图差多少？差在哪几段？

和 _diag_vs_official.py 的区别：那个量的是"站点在不在走廊上"，
这个量的是**真正画出来的那条线**（build_line_points_ex 的渲染点列，
含换乘站走廊偏移、替身点、折点）跟官方走廊的重合度。

两个方向都要量：
  A 路径→走廊：我的线有没有跑到官方走廊外面去
  B 走廊→路径：官方走廊有没有一段我压根没覆盖（★ 这个才是"走向不对"）
     cov = 走廊点里离我的线 <20px 的比例。官方线宽≈30px ⇒ cov 该 ≥0.9

用法：
    python tools/_diag_line_vs_official.py
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT.parent / "软件" / "data"

ST = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
LINES = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))["lines"]
CLOUD = json.loads((DATA / "trace_cloud.json").read_text(encoding="utf-8"))

import core.data_manager as CDM                                   # noqa: E402
CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"

from ui.map_view import build_line_points_ex                      # noqa: E402


def path_of(line_id, seq):
    """拿到真正画出来的点列"""
    try:
        out = build_line_points_ex(line_id, seq, ST, want_keys=True)
    except TypeError:
        out = build_line_points_ex(line_id, seq, ST)
        return np.asarray(out[0], float), None
    pts, _elbows, keys = out[0], out[1], out[2]
    P = np.array([[p.x(), p.y()] for p in pts], float)
    return P, keys


def densify_labelled(P, keys, step=6.0):
    """逐**段**插值成密集点，并给每个密集点带上它所属的段。

    ★★ 别用"索引比例"把密集点硬套回原段：densify 是按弧长等距的，
       长段点多、短段点少，索引比例一乘就整体错位
       （实测会把偏差归到不相干的段上，报出 268px 这种假数）。
    """
    xs, ys, labs = [], [], []
    nk = len(keys) if keys else 0
    for j in range(1, len(P)):
        a, b = P[j - 1], P[j]
        L = float(np.hypot(b[0] - a[0], b[1] - a[1]))
        n = max(1, int(L / step))
        t = np.linspace(0.0, 1.0, n, endpoint=False)
        for tt in t:
            xs.append(a[0] + (b[0] - a[0]) * tt)
            ys.append(a[1] + (b[1] - a[1]) * tt)
            labs.append(keys[j] if j < nk else "")
    return np.column_stack([xs, ys]), labs


rows = []
for l in LINES:
    lid = str(l.get("id", ""))
    seq = l.get("stations") or []
    C = np.asarray(CLOUD.get(lid) or [], float)
    if len(C) < 200:
        continue
    P, keys = path_of(lid, seq)
    if len(P) < 2:
        continue
    Pd, _labs = densify_labelled(P, keys)

    tp = cKDTree(Pd)
    tc = cKDTree(C)
    # A 我的线 → 官方走廊
    dA, _ = tc.query(Pd, k=1)
    # B 官方走廊 → 我的线
    dB, _ = tp.query(C, k=1)

    # 最差段：把 A 按"属于哪两站"归组
    worst = None
    if keys:
        seg = {}
        for i, k in enumerate(keys):
            if not k:
                continue
            seg.setdefault(k, []).append(dA[i] if i < len(dA) else 0.0)
        if seg:
            k, v = max(seg.items(), key=lambda kv: float(np.median(kv[1])))
            worst = (k, float(np.median(v)))

    rows.append({
        "lid": lid,
        "name": l.get("name") or lid,
        "n": len(seq),
        "A_med": float(np.median(dA)), "A_p90": float(np.percentile(dA, 90)),
        "A_max": float(dA.max()),
        "B_med": float(np.median(dB)), "B_p90": float(np.percentile(dB, 90)),
        "cov": float((dB < 20.0).mean()),
        "worst": worst,
    })

rows.sort(key=lambda r: r["cov"])
print("=" * 100)
print("线路走向 vs 官方走廊（按「覆盖度」从最差排到最好）")
print("  A = 我的线离官方走廊多远(px)   B = 官方走廊离我的线多远(px)   cov = 官方走廊被覆盖的比例")
print("=" * 100)
print("%-10s %-5s | %-20s | %-20s | %-7s | %s"
      % ("线", "站数", "A 我的线→官方 中位/P90/最大", "B 官方→我的线 中位/P90", "cov", "最离谱的一段"))
print("-" * 100)
for r in rows:
    w = r["worst"]
    wtxt = ("%s (%.0fpx)" % (w[0], w[1])) if w else "-"
    flag = "  ★★" if r["cov"] < 0.7 else ("  ★" if r["cov"] < 0.9 else "")
    print("%-10s %-5d | %6.1f %6.1f %7.1f | %6.1f %6.1f %7.1f | %6.0f%% | %s%s"
          % (r["name"][:10], r["n"], r["A_med"], r["A_p90"], r["A_max"],
             r["B_med"], r["B_p90"], r["B_med"], r["cov"] * 100, wtxt, flag))

print("-" * 100)
if rows:
    print("全图：覆盖度中位 %.0f%% ｜ A 中位 %.1fpx ｜ B 中位 %.1fpx"
          % (np.median([r["cov"] for r in rows]) * 100,
             np.median([r["A_med"] for r in rows]),
             np.median([r["B_med"] for r in rows])))
    bad = [r for r in rows if r["cov"] < 0.7]
    print("覆盖度 <70%% 的线（走向明显不对）共 %d 条：%s"
          % (len(bad), "、".join(r["name"] for r in bad)))
print()
print("判读：cov 该 ≥90%。cov 低 = 官方走了那条路、我的线没走 ⇒ 走向不对，不是微调能救。")
print("      但 ★ 真正没得洗的是 **A 的 P90/最大** —— 我的线跑到官方走廊外面去了，")
print("      那一段一定是我的线画错了（走廊是从官方图描的，官方不会错）。")

# ---- 段级排名：把每条线里偏差最大的那些段挑出来 ----
SEGS = []
for l in LINES:
    lid = str(l.get("id", ""))
    seq = l.get("stations") or []
    C = np.asarray(CLOUD.get(lid) or [], float)
    if len(C) < 200:
        continue
    P, keys = path_of(lid, seq)
    if len(P) < 2 or not keys:
        continue
    Pd, labs = densify_labelled(P, keys)
    tc = cKDTree(C)
    dA, _ = tc.query(Pd, k=1)
    per = {}
    for i, k in enumerate(labs):
        if k:
            per.setdefault(k, []).append(dA[i])
    for k, v in per.items():
        if len(v) < 3:
            continue
        SEGS.append((float(np.median(v)), float(np.max(v)), k, len(v)))

SEGS.sort(reverse=True)
print()
print("=" * 100)
print("★ 段级：**离官方走廊最远的 30 段**（我的线跑出了官方走廊多远，中位/最大 px）")
print("=" * 100)
for med, mx, k, n in SEGS[:30]:
    parts = k.split("|")
    who = "%s号线 %s→%s" % (parts[0], parts[1], parts[2]) if len(parts) >= 3 else k
    print("   中位 %6.1f px   最大 %7.1f px   %s" % (med, mx, who))
print("-" * 100)
if SEGS:
    print("中位偏差 >30px 的段：%d 段（官方线宽才 30px ⇒ 这些段整段都在官方线外面）"
          % len([s for s in SEGS if s[0] > 30]))
    print("中位偏差 >15px 的段：%d 段" % len([s for s in SEGS if s[0] > 15]))
    print("(共统计 %d 段)" % len(SEGS))
