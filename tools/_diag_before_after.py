# -*- coding: utf-8 -*-
"""诊断：v2.6.17 那次"布局重排"到底把图改好了还是改坏了？

对照三组坐标：
  NOW = 软件/data/stations.json          （现状，v2.6.17 求解器产物）
  OLD = 源码/data/stations.json.bak_relayout_20260930_021126（重排前 = 官方像素系真值）
  CLOUD = 软件/data/trace_cloud.json     （官方走廊点云，当作"标准答案"的参照）

只读，不改任何数据。

用法：
    python tools/_diag_before_after.py
"""
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"


def load_stations(p):
    d = json.loads(Path(p).read_text(encoding="utf-8"))
    return d["stations"] if isinstance(d, dict) and "stations" in d else d


NOW = load_stations(DATA / "stations.json")
BAK = sorted((ROOT / "data").glob("stations.json.bak_relayout_*"))
CLOUD = json.loads((DATA / "trace_cloud.json").read_text(encoding="utf-8"))
LINES = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))["lines"]


def octi(ang):
    a = abs(ang) % 90.0
    return min(a, 90.0 - a)


def metrics(order, S, pts):
    pos = [(S[s]["x"], S[s]["y"]) for s in order
           if s in S and S[s].get("x") is not None]
    if len(pos) < 3 or len(pts) == 0:
        return None
    P = np.asarray(pos, float)
    C = np.asarray(pts, float)

    d = np.sqrt(((P[:, None, :] - C[None, :, :]) ** 2).sum(-1)).min(axis=1)
    V = np.diff(P, axis=0)
    L = np.hypot(V[:, 0], V[:, 1]); L[L < 1e-6] = 1e-6
    ang = np.degrees(np.arctan2(V[:, 1], V[:, 0]))
    dev = np.array([octi(a) for a in ang])
    return {
        "n": len(P),
        "octi": float((dev <= 5.0).mean()),
        "jog": float((dev > 5.0).mean()),
        "med": float(np.median(d)),
        "p90": float(np.percentile(d, 90)),
        "cv": float(L.std() / L.mean()),
        "ratio": float(L.max() / L.mean()),
    }


def summarise(name, S):
    rs = []
    for l in LINES:
        lid = str(l.get("id", ""))
        m = metrics(l.get("stations") or [], S, CLOUD.get(lid) or [])
        if m:
            rs.append(m)
    if not rs:
        return None
    return {
        "name": name,
        "lines": len(rs),
        "octi": np.mean([r["octi"] for r in rs]),
        "jog": np.mean([r["jog"] for r in rs]),
        "med": np.median([r["med"] for r in rs]),
        "p90": np.median([r["p90"] for r in rs]),
        "cv": np.mean([r["cv"] for r in rs]),
        "ratio": np.mean([r["ratio"] for r in rs]),
    }


def show(r):
    if not r:
        print("  （算不出来）")
        return
    print("  %-10s 线数%2d | 八向合规 %5.1f%% | 毛刺 %5.1f%% | 离走廊 中位%5.1f P90%6.1f | 站距CV %.3f | 最长/均 %.2f"
          % (r["name"], r["lines"], r["octi"] * 100, r["jog"] * 100,
             r["med"], r["p90"], r["cv"], r["ratio"]))


print("=" * 96)
print("v2.6.17 布局重排 前 / 后 对照（越低越好：毛刺、离走廊、CV、最长/均；越高越好：八向合规）")
print("=" * 96)
now = summarise("★ 现在", NOW)
show(now)
print("-" * 96)
for b in BAK:
    tag = b.name.split("bak_relayout_")[-1]
    show(summarise(tag, load_stations(b)))
print("=" * 96)
print()
print("判读：")
print("  若「重排前」八向合规明显高于「现在」⇒ v2.6.17 的求解器把官方的横平竖直给拧歪了，")
print("  这就是'和原图不相符'的根，解法是回到官方真值、只解冲突不全局重排。")
