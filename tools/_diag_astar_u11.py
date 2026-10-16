# -*- coding: utf-8 -*-
"""u11 顽固段诊断：A* 原始路径 vs 当前描线的偏移对比 + 目检图。只读。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image, ImageDraw

import fix_fit_official as F
import fix_fit_user9 as U
import fix_retrace_from_official as FR

_e = FR.COLORS.get("10")
if isinstance(_e, dict):
    _e["colors"] = [[(247, 117, 148), 999]]
else:
    FR.COLORS["10"] = {"colors": [[(247, 117, 148), 999]]}

TARGETS = [
    "3|老街|晒布", "9|下梅林|梅村", "9|高新南|红树湾南", "9|红树湾南|深湾",
]

for key in TARGETS:
    lid, a, b = key.split("|")
    A = F.corridor_pt(a, lid)
    B = F.corridor_pt(b, lid)
    blk = U.mask_big(lid, A, B)
    if blk is None:
        print(key, "掩膜建不起来")
        continue
    m, x0, y0 = blk
    P, why = U.trace_seg2(lid, A, B)
    print("=== %s === A*=%s" % (key, why))
    tr = (U.DOC.get("traced") or {}).get(key)
    print("  现描线(%d点): %s" % (len(tr or []), (tr or [])[:4]))
    if P is None:
        continue
    D = U.__dict__.get("_D_cache")  # noqa
    # A* 路径偏移剖面（不 dedup、不 trim）
    Dm = __import__("scipy.ndimage", fromlist=["distance_transform_edt"]).distance_transform_edt(m)
    vals = F.offsets(Dm, x0, y0, P)
    v = np.asarray([x for x in vals if x is not None])
    print("  A*原始(%d点) 偏移 p50=%.1f p90=%.1f max=%.1f" % (
        len(P), float(np.percentile(v, 50)), float(np.percentile(v, 90)), float(v.max())))
    # 目检：掩膜灰底 + A* 路径黑线 + 现描线红点
    img = np.stack([np.where(m, 235, 40)] * 3, axis=2).astype(np.uint8)
    im = Image.fromarray(img)
    dr = ImageDraw.Draw(im)
    pts = [(x - x0, y - y0) for x, y in P]
    dr.line(pts, fill=(0, 0, 0), width=2)
    for x, y in (tr or []):
        dr.ellipse([x - x0 - 3, y - y0 - 3, x - x0 + 3, y - y0 + 3], outline=(255, 0, 0), width=2)
    im.save(str(Path(__file__).parent / ("_astar11_%s_%s_%s.png" % (lid, a, b))))
    print("  [图] _astar11_%s_%s_%s.png  (黑=A*原始, 红=现描线)" % (lid, a, b))
