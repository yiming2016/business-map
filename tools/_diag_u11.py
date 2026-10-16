# -*- coding: utf-8 -*-
"""u11 诊断：四段的偏移沿弧长分布（掐头去尾各留 0/10/.../100% 的量点）
+ 每段出叠加目检图（真渲染黑线压官方原图）。只读，不改数据。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import fix_fit_official as F
import fix_fit_user9 as U

TARGETS = [
    "3|老街|晒布", "9|下梅林|梅村", "9|高新南|红树湾南", "9|红树湾南|深湾",
]

for key in TARGETS:
    lid, a, b = key.split("|")
    A = F.corridor_pt(a, lid)
    B = F.corridor_pt(b, lid)
    poly = F.drawn_polyline(lid, U.seq_of(lid))
    seg = F.slice_between(poly, A, B)
    blk = F.line_mask_stats(lid, A, B)
    if blk is None:
        print(key, "掩膜不可信")
        continue
    D, x0, y0 = blk
    Q = F.resample(seg, 6.0)
    acc = [0.0]
    for k in range(1, len(Q)):
        acc.append(acc[-1] + float(np.hypot(*(Q[k] - Q[k - 1]))))
    total = acc[-1]
    vals = F.offsets(D, x0, y0, Q)
    prof = []
    for frac in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        want = frac * total
        k = int(np.argmin([abs(t - want) for t in acc]))
        v = vals[k]
        prof.append("%%%.0f=%.1f" % (frac * 100, v) if v is not None else "%%%.0f=?" % (frac * 100))
    print("%-20s 段长=%.0f  %s" % (key, total, "  ".join(prof)))
    # 端点锚位离带子中心线多远（不掐）
    for nm, P in ((a, A), (b, B)):
        vv = F.offsets(D, x0, y0, [P])
        print("    锚位 %-6s (%.0f,%.0f) 偏中心=%s" % (
            nm, P[0], P[1], "%.1f" % vv[0] if vv[0] is not None else "出块"))
