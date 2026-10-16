# -*- coding: utf-8 -*-
"""只读：量出原图每段"肘形折点"放在**哪一侧**（a 端还是 b 端）。

背景（用户原话）：「你很多的弯曲方向和原图都是相反的」。

我们的 `octilinear_waypoints_tagged()` 把两站之间拆成
      a →(45°斜线 m 长)→ 再直线到 b      （= 斜线在 a 端）
另一种同样合法的八向画法是
      a →直线→ (45°斜线 m 长)→ b          （= 斜线在 b 端）
两者总长一样、都符合"横/竖/45°"，但**形状是镜像的**。
到底原图用哪种，只能去原图上量。

做法：对每条线建"该线颜色的距离场" DF（到最近同色像素的距离），
把两个候选路径都密集采样，比"采样点平均 DF" —— 小的那个就是原图的画法。
端点附近被站点图标盖住，所以掐掉两端 R_TRIM 像素。

产物：`data/elbow_sides.json`  {"<line>|<a>|<b>": "a"|"b"}（只写**结论明确**的）
用法：
    python tools/measure_elbow_side.py            # 只量、打印、写 json
"""
import json
import sys
import os
import math
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

import numpy as np                      # noqa: E402
from PIL import Image                   # noqa: E402
from scipy import ndimage               # noqa: E402

from PySide6.QtWidgets import QApplication          # noqa: E402
from ui.metro_render import OCTI_TOL, OCTI_TOL_PX   # noqa: E402
from ui.map_view import build_line_points_ex        # noqa: E402

Image.MAX_IMAGE_PIXELS = None
R_TRIM = 46          # 两端各掐掉这么多像素（站点图标 + 圆角区）
STEP = 4.0           # 采样步长
MIN_GAIN = 1.0       # 两条候选的平均 DF 差多少才算"结论明确"


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def main():
    QApplication.instance() or QApplication(sys.argv)   # QPointF 本身不要，保险起见
    st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj

    img = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)
    H, W = img.shape[:2]

    DF = {}
    for L in lines:
        lid = str(L.get("id"))
        r, g, b = hex2rgb(L.get("color") or "#888888")
        m = (np.abs(img[:, :, 0] - r) + np.abs(img[:, :, 1] - g)
             + np.abs(img[:, :, 2] - b)) <= 20
        DF[lid] = ndimage.distance_transform_edt(~ndimage.binary_erosion(m, np.ones((3, 3))))
        print("[DF] %-6s 同色像素 %d" % (lid, int(m.sum())))

    def score(lid, pts):
        d = DF[lid]
        tot, k = 0.0, 0
        # 累进弧长，掐头去尾
        segs = []
        L = 0.0
        for i in range(1, len(pts)):
            x0, y0 = pts[i - 1]
            x1, y1 = pts[i]
            l = math.hypot(x1 - x0, y1 - y0)
            segs.append((x0, y0, x1, y1, l))
            L += l
        if L <= 2 * R_TRIM + 8:
            return None, 0.0
        acc = 0.0
        for x0, y0, x1, y1, l in segs:
            if l < 1e-6:
                continue
            n = max(1, int(l / STEP))
            for j in range(n + 1):
                t = (j / n) * l
                pos = acc + t
                if pos < R_TRIM or pos > L - R_TRIM:
                    continue
                x = x0 + (x1 - x0) * (t / l)
                y = y0 + (y1 - y0) * (t / l)
                ix, iy = int(round(x)), int(round(y))
                if 0 <= ix < W and 0 <= iy < H:
                    tot += float(d[iy, ix])
                    k += 1
            acc += l
        if k == 0:
            return None, 0.0
        return tot / k, float(k)

    out = {}
    rows = []
    n_elbow = 0
    for L in lines:
        lid = str(L.get("id"))
        seq = [s for s in (L.get("stations") or []) if s in st]
        if len(seq) < 2:
            continue
        # ★★ 必须按**真正画出来的点段**去量，不能按"站到站的直线"：
        #    换乘站有走廊偏移、还会插替身点，直线段跟画出来的段根本不是一条，
        #    量出来的方向会贴到"压根不需要折"的段上（实测 66 条 b 只生效 8 条）。
        pts, _ebl, keys = build_line_points_ex(lid, seq, st, want_keys=True)
        for i in range(1, len(pts)):
            key = keys[i] if i < len(keys) else ""
            if not key:
                continue
            a_pt, b_pt = pts[i - 1], pts[i]
            ax, ay = float(a_pt.x()), float(a_pt.y())
            bx, by = float(b_pt.x()), float(b_pt.y())
            dx, dy = bx - ax, by - ay
            adx, ady = abs(dx), abs(dy)
            big = max(adx, ady)
            if big < 1e-6 or adx < 1e-6 or ady < 1e-6:
                continue
            if min(adx, ady) < OCTI_TOL_PX:
                continue
            if abs(adx - ady) <= big * OCTI_TOL:
                continue
            n_elbow += 1
            mm = min(adx, ady)
            sx = 1.0 if dx > 0 else -1.0
            sy = 1.0 if dy > 0 else -1.0
            cand_a = [(ax, ay), (ax + sx * mm, ay + sy * mm), (bx, by)]
            cand_b = [(ax, ay), (bx - sx * mm, by - sy * mm), (bx, by)]
            sa, ka = score(lid, cand_a)
            sb, kb = score(lid, cand_b)
            if sa is None or sb is None:
                continue
            nm_a, nm_b = key.split("|")[1], key.split("|")[2]
            rows.append((sa - sb, lid, nm_a, nm_b, sa, sb, mm))
            if sb + MIN_GAIN < sa:
                out[key] = "b"
            elif sa + MIN_GAIN < sb:
                out[key] = "a"

    rows.sort()
    n_b = sum(1 for r in rows if r[0] > MIN_GAIN)
    n_a = sum(1 for r in rows if r[0] < -MIN_GAIN)
    n_amb = len(rows) - n_b - n_a
    print("\n需要插肘形折点的段 %d；可测 %d" % (n_elbow, len(rows)))
    print("  原图偏『斜线在 b 端』: %d" % n_b)
    print("  原图偏『斜线在 a 端』: %d  （= 我们现在写死的画法）" % n_a)
    print("  两条候选差不多（看不出来）: %d" % n_amb)

    print("\n最明显的『原图是 b 端』前 25 条（gain 越大越确定）：")
    for r in [x for x in rows if x[0] > MIN_GAIN][-25:]:
        print("   %-6s %-8s→%-8s  斜长%4d  a端DF %6.1f  b端DF %6.1f  省 %5.1f"
              % (r[1], r[2], r[3], r[6], r[4], r[5], r[0]))
    print("\n最明显的『原图是 a 端』前 12 条：")
    for r in [x for x in rows if x[0] < -MIN_GAIN][:12]:
        print("   %-6s %-8s→%-8s  斜长%4d  a端DF %6.1f  b端DF %6.1f  省 %5.1f"
              % (r[1], r[2], r[3], r[6], r[4], r[5], -r[0]))

    p = SRC / "data" / "elbow_sides.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True),
                 encoding="utf-8")
    print("\n写出 %s（%d 条结论明确）" % (p, len(out)))


main()
