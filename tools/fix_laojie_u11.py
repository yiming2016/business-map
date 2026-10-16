# -*- coding: utf-8 -*-
"""u11 手写 3|老街|晒布 描线：A* 原始路径掐掉两端各 40px（药丸/站洞区
D 尺不可信），中段重采样 15px + RDP(4)，钉回两端锚位。写 软件/data。"""
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fix_fit_official as F
import fix_fit_user9 as U
import fix_retrace_from_official as FR

KEY = "3|老街|晒布"
lid, a, b = KEY.split("|")

A = F.corridor_pt(a, lid)
B = F.corridor_pt(b, lid)
P, why = U.trace_seg2(lid, A, B)
print("A*:", why)
assert P is not None

# 弧长
d = np.hypot(np.diff(P[:, 0]), np.diff(P[:, 1]))
acc = np.concatenate([[0], np.cumsum(d)])
total = acc[-1]
keep = (acc >= 40) & (acc <= total - 40)
Q = P[keep]
print("中段 %d/%d 点" % (len(Q), len(P)))

# 重采样 15px
def resample(P, step=15.0):
    out = [P[0]]
    dist = 0.0
    for i in range(1, len(P)):
        seg = np.hypot(*(P[i] - P[i - 1]))
        while dist + seg >= step:
            t = (step - dist) / seg
            out.append(P[i - 1] + t * (P[i] - P[i - 1]))
            seg = seg - (step - dist)
            dist = 0.0
            P = P[i - 1:]
            i = 1
            break
        dist += seg
        # 简化：直接线性重采
    out.append(P[-1] if len(P) else out[-1])
    return np.asarray(out)

# 更稳的重采：按弧长插值
def resample_arc(P, step=15.0):
    d = np.hypot(np.diff(P[:, 0]), np.diff(P[:, 1]))
    acc = np.concatenate([[0], np.cumsum(d)])
    n = int(acc[-1] / step)
    ts = np.linspace(0, acc[-1], max(n, 8))
    x = np.interp(ts, acc, P[:, 0])
    y = np.interp(ts, acc, P[:, 1])
    return np.column_stack([x, y])

Q = resample_arc(Q, 15.0)
Q = FR.rdp(Q, 4.0)
Q = np.vstack([A, Q, B])
# 去零长
out = [Q[0]]
for p in Q[1:]:
    if np.hypot(*(p - out[-1])) > 2.0:
        out.append(p)
Q = np.asarray(out)
print("最终 %d 点:" % len(Q), [[round(float(x), 1), round(float(y), 1)] for x, y in Q])

# 直接量偏移（掩膜正尺，中段 trim 34）
blk = U.mask_big(lid, A, B)
m, x0, y0 = blk
import scipy.ndimage as ndi
D = ndi.distance_transform_edt(m)
vals = F.offsets(D, x0, y0, F.trim([tuple(p) for p in Q]))
v = np.asarray([x for x in vals if x is not None])
print("手写路径偏移 p50=%.1f p90=%.1f max=%.1f" % (
    np.percentile(v, 50), np.percentile(v, 90), v.max()))

if "--apply" not in sys.argv:
    print("（预演）")
    sys.exit(0)

bak = U.DATA / ("lines.json.bak_lj_%s" % time.strftime("%Y%m%d_%H%M%S"))
shutil.copy(U.DATA / "lines.json", bak)
DOC = U.DOC
DOC.setdefault("traced", {})[KEY] = [[round(float(x), 1), round(float(y), 1)] for x, y in Q]
DOC["octi_off"] = sorted(set(DOC.get("octi_off") or []) | {KEY})
tmp = U.DATA / "lines.json.tmp"
tmp.write_text(json.dumps(DOC, ensure_ascii=False, indent=1), encoding="utf-8")
tmp.replace(U.DATA / "lines.json")
print("[写入] %s" % (U.DATA / "lines.json"))
