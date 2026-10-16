# -*- coding: utf-8 -*-
"""只读探针：每一条线的"官方色掩膜"到底可不可靠。

判据：合格掩膜的带宽应≈22px（半宽 hw≈11）。hw 明显偏小 = 掩膜是细丝/噪声 ⇒ 量尺不可信。

同时沿"软件真正画出来的线"采样官方原图颜色，看真实填充色是什么（浅色线的主色可能取错）。

用法：python tools/_probe_mask.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, label

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))
import core.data_manager as CDM
CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"
from ui.map_view import build_line_points_ex
from ui import metro_render as MR

OFF = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)
COL = json.loads((ROOT / "_tmp_official_colors.json").read_text(encoding="utf-8"))

dm = CDM.get_data_manager()
st = dm.all_stations()
doc = dm.lines_doc
lines = doc.get("lines") or []


def drawn(lid, seq):
    pts, ebl = build_line_points_ex(lid, seq, st)
    w = MR.octilinear_waypoints_tagged(pts, ebl)
    return [(float(p.x()), float(p.y())) for p, _ in w]


def resample(P, step=8.0):
    out = []
    for i in range(len(P) - 1):
        (x0, y0), (x1, y1) = P[i], P[i + 1]
        L = float(np.hypot(x1 - x0, y1 - y0))
        n = max(1, int(np.ceil(L / step)))
        for k in range(n):
            t = k / n
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    out.append(P[-1])
    return np.asarray(out, dtype=float)


print("%-4s %-16s %9s %6s %6s %9s   %s" %
      ("线", "名称", "主色像素", "hw", "带宽", "最大连通域", "线上真实主色(±25px采样)"))
for L in lines:
    lid = str(L.get("id"))
    seq = [n for n in (L.get("stations") or []) if n in st]
    if len(seq) < 2:
        continue
    e = COL.get(lid)
    if not isinstance(e, dict):
        print("%-4s 色表缺失" % lid)
        continue
    c = e["colors"][0][0]
    M = (np.abs(OFF - np.array(c)).sum(axis=2) < 48)
    npx = int(M.sum())
    if npx == 0:
        print("%-4s %-16s %9d  掩膜为空" % (lid, e.get("name"), 0))
        continue
    D = distance_transform_edt(M)
    hw = float(np.median(D[M]))
    lab, n = label(M)
    if n:
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        big = int(sizes.max())
    else:
        big = 0

    # 采样"我画出来的线"±25px 内的官方颜色
    try:
        poly = drawn(lid, seq)
        S = resample(poly, 8.0)
        cnt = Counter()
        r = 25
        for x, y in S[::2]:
            xi, yi = int(round(x)), int(round(y))
            sub = OFF[max(0, yi - r):yi + r, max(0, xi - r):xi + r]
            if sub.size == 0:
                continue
            flat = sub.reshape(-1, 3)
            for col, k in zip(*np.unique(flat, axis=0, return_counts=True)):
                if k >= 8:
                    cnt[tuple(int(v) for v in col)] += int(k)
        top = cnt.most_common(3)
        tops = " ".join("%s×%d" % (list(t[0]), t[1]) for t in top)
    except Exception as ex:
        tops = "采样失败:" + repr(ex)
    print("%-4s %-16s %9d %6.1f %6.1f %9d   %s" %
          (lid, e.get("name"), npx, hw, hw * 2, big, tops))
