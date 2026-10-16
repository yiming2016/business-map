# -*- coding: utf-8 -*-
"""只读诊断：2 号线「后海」附近（登良→后海→科苑）到底歪在哪。

输出两样东西：
  ① 控制台：逐点的「离官方带中心偏多少」统计 + 最大偏差点坐标；
  ② 图片：官方原图裁一小块 + 我的线用**洋红色**叠上去，自己看。

★ 判据用官方向量图的**同色像素掩膜 → 距离变换**（与 _diag_fit_center 同一把尺）：
  带内每点到带边缘的距离 D；带子中心线的 D ≈ 半宽 hw。
  「偏中心量 = hw - D」，>0 = 偏向带边（越贴边越危险）。
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))
import core.data_manager as CDM          # noqa: E402
CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"

from ui.map_view import build_line_points_ex, line_station_xy   # noqa: E402
from ui import metro_render as MR                               # noqa: E402

LID = "2"
SEQS = [("登良", "后海"), ("后海", "科苑")]

OFF_IMG = Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")
OFF = np.asarray(OFF_IMG).astype(np.int16)
COL = json.loads((ROOT / "_tmp_official_colors.json").read_text(encoding="utf-8"))

dm = CDM.get_data_manager()
st = dm.all_stations()
doc = dm.lines_doc
lines = {str(L.get("id")): L for L in (doc.get("lines") or [])}


def land(nm, lid):
    s = st[nm]
    x, y = line_station_xy(s, lid)
    d = (s.get("lanes") or {}).get(lid)
    if d:
        try:
            x, y = float(x) + float(d[0]), float(y) + float(d[1])
        except Exception:
            pass
    return (float(x), float(y))


def drawn_polyline(lid):
    L = lines[lid]
    seq = [n for n in (L.get("stations") or []) if n in st]
    pts, ebl = build_line_points_ex(lid, seq, st)
    w = MR.octilinear_waypoints_tagged(pts, ebl)
    return [(float(p.x()), float(p.y())) for p, _ in w]


def resample(P, step=4.0):
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


poly = drawn_polyline(LID)

# ---- 官方同色掩膜（2 号线 #B05000；同色线会互相干扰，这里只看距离，仅作参考）----
e = COL.get(LID)
c = e["colors"][0][0] if isinstance(e, dict) else e
M = (np.abs(OFF - np.array(c)).sum(axis=2) < 48)
D = distance_transform_edt(M)
hw = float(np.median(D[M]))
print("2 号线官方色 =", c, " 带宽 = %.1f px  半宽 hw = %.1f" % (hw * 2, hw))

print("\n%-14s %6s %7s %7s %7s   %s" %
      ("段", "采样", "偏中p50", "偏中p90", "偏中max", "最大偏差处 / 端点贴边"))
for a, b in SEQS:
    A, B = land(a, LID), land(b, LID)
    ia = int(np.argmin([np.hypot(x - A[0], y - A[1]) for x, y in poly]))
    ib = int(np.argmin([np.hypot(x - B[0], y - B[1]) for x, y in poly]))
    if ia > ib:
        ia, ib = ib, ia
    seg = poly[ia:ib + 1]
    S = resample(seg, 2.0)
    xi = np.clip(np.round(S[:, 0]).astype(int), 0, OFF.shape[1] - 1)
    yi = np.clip(np.round(S[:, 1]).astype(int), 0, OFF.shape[0] - 1)
    d_in = D[yi, xi]
    off = hw - d_in
    p50, p90 = (float(np.percentile(np.abs(off), q)) for q in (50, 90))
    kmax = int(np.argmax(np.abs(off)))
    print("%-14s %6d %7.1f %7.1f %7.1f   (%7.1f,%7.1f) D=%.1f | 起 D=%.1f 末 D=%.1f" %
          ("%s→%s" % (a, b), len(S), p50, p90, float(np.abs(off).max()),
           S[kmax][0], S[kmax][1], d_in[kmax], d_in[0], d_in[-1]))
    print("     实际端点(锚位)  A=(%.1f,%.1f)  B=(%.1f,%.1f)" %
          (A[0], A[1], B[0], B[1]))
    print("     我的折线端点    (%.1f,%.1f) → (%.1f,%.1f)  折线点数=%d" %
          (poly[ia][0], poly[ia][1], poly[ib][0], poly[ib][1], len(seg)))

# ---- 叠加出图 ----
xs = [p[0] for p in poly]
ys = [p[1] for p in poly]
cx, cy = land("后海", LID)
R = 900
box = (int(cx - R), int(cy - R), int(cx + R), int(cy + R))
crop = OFF_IMG.crop(box).copy()
dr = ImageDraw.Draw(crop)


def to_img(p):
    return (p[0] - box[0], p[1] - box[1])


for i in range(len(poly) - 1):
    dr.line([to_img(poly[i]), to_img(poly[i + 1])], fill=(255, 0, 200), width=3)

for nm in ("登良", "后海", "科苑"):
    p = land(nm, LID)
    ip = to_img(p)
    dr.ellipse([ip[0] - 10, ip[1] - 10, ip[0] + 10, ip[1] + 10],
               outline=(0, 160, 255), width=3)

crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
out = ROOT / "_tmp_houhai.png"
crop.save(out)
print("\n叠加图已存：", out, crop.size,
      "（蓝色圈=站点锚位 洋红=我的线）")
