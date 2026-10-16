# -*- coding: utf-8 -*-
"""独立交叉验证：我的线到底离官方带子中心多远（不用 W2 那个估计）。

方法（和 fix_fit_official 完全独立）：
  在采样点周围 61×61 的窗口里找**距离变换的局部极大**（= 带子横截面的中心），
  再量点到那个中心的欧氏距离。带子中心处的局部极大值应 ≈ 带半宽。

若此法给出"距离 ≈ 0"而 fix_fit_official 给出 10 ⇒ 是 fix_fit_official 的尺错了；
若两者一致 ⇒ 线是真的偏了。

用法：python tools/_probe_fit_xcheck.py [线号]
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_closing, distance_transform_edt, label

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))
import core.data_manager as CDM
CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"
from ui.map_view import build_line_points_ex

OFF = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)
import json
COLORS = json.loads((ROOT / "_tmp_official_colors.json").read_text(encoding="utf-8"))

ONLY = sys.argv[1] if len(sys.argv) > 1 else "1"

dm = CDM.get_data_manager()
ST = dm.all_stations()
LINES = dm.lines_doc.get("lines") or []
TOL = 48
MARGIN = 200.0


def corridor_xy(st, lid):
    x, y = float(st.get("x", 0)), float(st.get("y", 0))
    for b in (st.get("alt_bodies") or []):
        if str(b.get("line") or "") == str(lid):
            try:
                x, y = float(b["x"]), float(b["y"])
            except Exception:
                break
    d = (st.get("lanes") or {}).get(str(lid))
    if d:
        try:
            x, y = x + float(d[0]), y + float(d[1])
        except Exception:
            pass
    return x, y


def block(lid, A, B):
    x0 = max(0, int(min(A[0], B[0]) - MARGIN))
    y0 = max(0, int(min(A[1], B[1]) - MARGIN))
    x1 = min(8000, int(max(A[0], B[0]) + MARGIN))
    y1 = min(8000, int(max(A[1], B[1]) + MARGIN))
    c = (COLORS.get(lid) or {}).get("colors")[0][0]
    blk = OFF[y0:y1, x0:x1]
    m = np.abs(blk - np.array(c, dtype=np.int16)).sum(axis=2) < TOL
    m = binary_closing(m, structure=np.ones((9, 9)))
    lab, n = label(m)
    if n > 1:
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        m = (lab == int(sizes.argmax()))
    D = distance_transform_edt(m)
    return m, D, x0, y0


def resample(P, step=6.0):
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


print("线号 %s" % ONLY)
for L in LINES:
    lid = str(L.get("id"))
    if lid != ONLY:
        continue
    seq = [n for n in (L.get("stations") or []) if n in ST]
    pts, ebl = build_line_points_ex(lid, seq, ST)
    from ui import metro_render as MR
    poly = [(float(p.x()), float(p.y())) for p, _ in MR.octilinear_waypoints_tagged(pts, ebl)]
    # 每 3 段抽 1 段
    for i in range(0, len(seq) - 1, 3):
        a, b = seq[i], seq[i + 1]
        A = corridor_xy(ST[a], lid)
        B = corridor_xy(ST[b], lid)
        m, D, x0, y0 = block(lid, A, B)
        ia = int(np.argmin([np.hypot(x - A[0], y - A[1]) for x, y in poly]))
        ib = int(np.argmin([np.hypot(x - B[0], y - B[1]) for x, y in poly]))
        if ia > ib:
            ia, ib = ib, ia
        seg = poly[ia:ib + 1]
        Q = resample(seg, 6.0)
        if len(Q) < 8:
            continue
        Q = Q[len(Q) // 4: -len(Q) // 4] if len(Q) > 12 else Q
        W2 = 2.0 * float(np.median(D[m]))
        r = 30
        rows = []
        for x, y in Q[::4]:
            xi, yi = int(round(x - x0)), int(round(y - y0))
            if xi < r or yi < r or xi >= D.shape[1] - r or yi >= D.shape[0] - r:
                continue
            win = D[yi - r:yi + r + 1, xi - r:xi + r + 1]
            j = int(np.argmax(win))
            cy, cx = divmod(j, win.shape[1])
            mx, my = xi - r + cx, yi - r + cy
            dist = float(np.hypot(mx - xi, my - yi))
            rows.append((float(D[yi, xi]), float(win.max()), dist))
        if not rows:
            continue
        arr = np.asarray(rows)
        print("  %-22s W2=%5.1f | D(点)中位%5.1f 局部极大中位%5.1f 点到局部极大中位%5.1f 最大%5.1f"
              % ("%s→%s" % (a, b), W2,
                 float(np.median(arr[:, 0])), float(np.median(arr[:, 1])),
                 float(np.median(arr[:, 2])), float(arr[:, 2].max())))
