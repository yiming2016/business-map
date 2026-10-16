# -*- coding: utf-8 -*-
"""诊断（可靠版）：直接从官方原图**按颜色**取出每条线的真实走向，再和我的线比。

为什么不用 trace_cloud.json（描线点云）当判据：
  ★ 它本身有缺失/噪声 —— 实测"13号线 科苑→粤海门"报出 262px 假偏差，
    把路径叠回官方图一看是重合的，只是那一段压根没被描到。
  所以判据只能用"官方原图 + 官方色"这种不会说谎的东西。

官方色是采样出来的（各站坐标附近 ±25px 的彩色众数），存在 _tmp_official_colors.json。

用法：
    python tools/_diag_line_color_truth.py [线号 ...]
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

ST = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
LINES = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))["lines"]
COLORS = json.loads((ROOT / "_tmp_official_colors.json").read_text(encoding="utf-8"))

import core.data_manager as CDM                                   # noqa: E402
CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"
from ui.map_view import build_line_points_ex                      # noqa: E402

OFF = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)


def official_mask(rgb, tol=48):
    """给出某个官方色在图上的所有像素坐标"""
    d = np.abs(OFF - np.array(rgb, dtype=np.int16)).sum(axis=2)
    ys, xs = np.nonzero(d < tol)
    return np.column_stack([xs, ys]).astype(float)


def densify(P, step=8.0):
    xs, ys = [], []
    for j in range(1, len(P)):
        a, b = P[j - 1], P[j]
        L = float(np.hypot(b[0] - a[0], b[1] - a[1]))
        n = max(1, int(L / step))
        for t in np.linspace(0, 1, n, endpoint=False):
            xs.append(a[0] + (b[0] - a[0]) * t)
            ys.append(a[1] + (b[1] - a[1]) * t)
    return np.column_stack([xs, ys])


want = [a for a in sys.argv[1:] if not a.startswith("-")] or \
       [str(l.get("id")) for l in LINES]

print("=" * 96)
print("我的线 vs 官方原图同色像素（可靠判据）")
print("  med/p90 = 我的路径点到官方同色像素的距离（官方线宽 30 ⇒ 中位该 ≤15px）")
print("  far%%    = 我路径点里，附近 120px 内根本找不到官方同色像素的比例（→ 那一段官方压根没这条路）")
print("=" * 96)
print("%-12s %-6s | %-16s | %-16s | %s" % ("线", "路径点", "med/p90(px)", "最远(px)", "far%"))
print("-" * 96)

for lid in want:
    l = next((x for x in LINES if str(x.get("id")) == lid), None)
    if l is None:
        continue
    info = COLORS.get(lid) or {}
    cols = info.get("colors") or []
    if not cols:
        print("%-12s  没有采到官方色，跳过" % (l.get("name") or lid))
        continue
    rgb = cols[0][0]
    M = official_mask(rgb)
    if len(M) < 500:
        print("%-12s  官方色 %s 像素太少(%d)，跳过" % (l.get("name") or lid, rgb, len(M)))
        continue
    tc = cKDTree(M)

    seq = l.get("stations") or []
    try:
        P = np.array([[p.x(), p.y()] for p in build_line_points_ex(lid, seq, ST, want_keys=True)[0]], float)
    except TypeError:
        P = np.array([[p.x(), p.y()] for p in build_line_points_ex(lid, seq, ST)[0]], float)
    if len(P) < 2:
        continue
    Pd = densify(P)
    d, _ = tc.query(Pd, k=1)
    far = float((d > 120).mean())
    flag = "  ★★" if np.median(d) > 25 or far > 0.08 else ("  ★" if np.median(d) > 15 else "")
    print("%-12s %-6d | %6.1f %6.1f | %6.1f | %5.1f%%%s"
          % ((l.get("name") or lid)[:12], len(Pd), np.median(d), np.percentile(d, 90),
             d.max(), far * 100, flag))

print("-" * 96)
print("注：同色的线会互相干扰（2↔8、4↔10↔有轨电车、16↔坪山云巴），那几条要看 far% 而非距离。")
