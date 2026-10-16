# -*- coding: utf-8 -*-
"""u12 手写描线：A* 原始路径掐两端各 40px（洞/药丸区）→ 弧长重采 15px →
RDP(4) → 钉回锚位 → 直接写 traced（跳过被邻段几何污染的渲染自检）。
写完用掩膜正尺量写入路径本身的偏移 + 出叠加目检图。
"""
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scipy.ndimage as ndi
import fix_fit_official as F
import fix_fit_user9 as U
import fix_retrace_from_official as FR

TARGETS = [
    "9|南山书城|深大南",
    "9|南油|南山书城",
    "9|粤海门|高新南",
    "11|南山|后海",
]

results = {}
for key in TARGETS:
    lid, a, b = key.split("|")
    A = F.corridor_pt(a, lid)
    B = F.corridor_pt(b, lid)
    P, why = U.trace_seg2(lid, A, B)
    if P is None:
        print("[跳] %s A*失败: %s" % (key, why))
        continue
    d = np.hypot(np.diff(P[:, 0]), np.diff(P[:, 1]))
    acc = np.concatenate([[0], np.cumsum(d)])
    total = acc[-1]
    Q = P[(acc >= 40) & (acc <= total - 40)]
    if len(Q) < 2:
        print("[跳] %s 中段太短" % key)
        continue
    # 弧长重采 15px
    dq = np.hypot(np.diff(Q[:, 0]), np.diff(Q[:, 1]))
    accq = np.concatenate([[0], np.cumsum(dq)])
    n = max(int(accq[-1] / 15.0), 6)
    ts = np.linspace(0, accq[-1], n)
    Q = np.column_stack([np.interp(ts, accq, Q[:, 0]), np.interp(ts, accq, Q[:, 1])])
    Q = FR.rdp(Q, 4.0)
    Q = np.vstack([A, Q, B])
    out = [Q[0]]
    for p in Q[1:]:
        if np.hypot(*(p - out[-1])) > 2.0:
            out.append(p)
    Q = np.asarray(out)
    # 量写入路径自身的偏移（trim 34 避开洞区）
    blk = U.mask_big(lid, A, B)
    if blk is not None:
        m, x0, y0 = blk
        D = ndi.distance_transform_edt(m)
        vals = F.offsets(D, x0, y0, F.trim([tuple(p) for p in Q]))
        v = np.asarray([x for x in vals if x is not None])
        p50, p90 = float(np.percentile(v, 50)), float(np.percentile(v, 90))
    else:
        p50 = p90 = -1
    results[key] = [[round(float(x), 1), round(float(y), 1)] for x, y in Q]
    print("[量] %-18s %d点 偏移 p50=%.1f p90=%.1f" % (key, len(Q), p50, p90))

if "--apply" not in sys.argv:
    print("（预演）")
    sys.exit(0)

bak = U.DATA / ("lines.json.bak_u12_%s" % time.strftime("%Y%m%d_%H%M%S"))
shutil.copy(U.DATA / "lines.json", bak)
print("[备份] %s" % bak.name)
DOC = U.DOC
for key, pts in results.items():
    DOC.setdefault("traced", {})[key] = pts
    DOC["octi_off"] = sorted(set(DOC.get("octi_off") or []) | {key})
    print("[写] %s (%d点)" % (key, len(pts)))
tmp = U.DATA / "lines.json.tmp"
tmp.write_text(json.dumps(DOC, ensure_ascii=False, indent=1), encoding="utf-8")
tmp.replace(U.DATA / "lines.json")
print("[写入] %s" % (U.DATA / "lines.json"))
