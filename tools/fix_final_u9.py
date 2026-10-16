# -*- coding: utf-8 -*-
"""fix_final_u9.py —— 锚位+重描组合拳（黄木岗/八卦岭/科苑）。

上一轮教训：锚位改了但旧描线没重描 ⇒ 端点 kink ⇒ 量尺变差被护栏拒。
本脚本把"改锚 + 重描受影响段"作为原子操作，验收标准：
  · 重描段：重采样内点 D 中位 ≥ 8（深居官方带）且 p90 ≤ 基线 + 1.0；
  · 邻段（只动锚不重描）：p90 ≤ 基线 + 2.0；
  · 任一失败 ⇒ 该站锚位与描线全部还原。
"""
import sys
import copy

import numpy as np
from scipy.ndimage import distance_transform_edt

sys.argv = [sys.argv[0]] if len(sys.argv) == 1 else sys.argv
APPLY = "--apply" in sys.argv

import fix_fit_user9 as U
import fix_fit_official as F
import fix_retrace_from_official as FR

ST, DOC = U.ST, U.DOC

# (站, 线, [dcorr_x, dcorr_y])
ANCHORS = [
    ("黄木岗", "7", (-5.5, -5.6)),
    ("八卦岭", "7", (-20.3, -21.6)),
    ("科苑",   "2", (0.0, -28.0)),      # dy 21→-7：官方带 y=5762
]
RETRACE = ["7|黄木岗|八卦岭", "7|八卦岭|红岭北", "2|后海|科苑"]
RDP_EPS, DEDUP = 4.0, 20.0


def seg_key_neighbors(key):
    lid, a, b = key.split("|")
    seq = U.seq_of(lid)
    out = []
    for nm in (a, b):
        if nm in seq:
            i = seq.index(nm)
            if i > 0:
                out.append("%s|%s|%s" % (lid, seq[i - 1], nm))
            if i + 1 < len(seq):
                out.append("%s|%s|%s" % (lid, nm, seq[i + 1]))
    return sorted(set(out))


def depth_med(key_points, lid, A, B):
    m, x0, y0 = U.mask_big(lid, A, B)
    if m is None:
        return -1.0
    D = distance_transform_edt(m)
    pts = np.array(key_points, dtype=float)
    ds = []
    for i in range(len(pts) - 1):
        p0, p1 = pts[i], pts[i + 1]
        n = max(2, int(float(np.hypot(*(p1 - p0))) / 6))
        for t in np.linspace(0, 1, n):
            q = p0 + (p1 - p0) * t
            xi, yi = int(round(q[0])) - x0, int(round(q[1])) - y0
            if 0 <= yi < D.shape[0] and 0 <= xi < D.shape[1]:
                ds.append(float(D[yi, xi]))
    return float(np.median(ds)) if ds else -1.0


def main():
    all_segs = sorted(set(RETRACE)
                      | {s for k in RETRACE for s in seg_key_neighbors(k)}
                      | {s for nm, lid, _ in ANCHORS
                         for s in seg_key_neighbors("%s|%s|%s" % (lid, nm, nm))})
    base = {k: U.measure(*k.split("|")) for k in all_segs}
    print("基线 p90：")
    for k in all_segs:
        print("  %-18s %s" % (k, "%.1f" % base[k][1] if base[k] else "?"))

    snaps = {}
    for nm, lid, corr in ANCHORS:
        old = list((ST[nm].get("lanes") or {}).get(lid, []))
        snaps[(nm, lid)] = (copy.deepcopy(old),
                            copy.deepcopy(DOC.get("traced", {}).get(
                                "%s|%s" % (lid, nm))) if False else None)
    snap_lanes = {(nm, lid): list((ST[nm].get("lanes") or {}).get(lid, []))
                  for nm, lid, _ in ANCHORS}
    snap_traced = {k: copy.deepcopy(DOC.get("traced", {}).get(k)) for k in RETRACE}
    snap_oo = list(DOC.get("octi_off") or [])

    if not APPLY:
        print("\n（预演——不写入）")
        return

    # 1) 锚位
    for nm, lid, corr in ANCHORS:
        old = snap_lanes[(nm, lid)]
        ST[nm].setdefault("lanes", {})
        if old:
            ST[nm]["lanes"][lid] = [old[0] + corr[0], old[1] + corr[1]] + list(old[2:])
        else:
            ST[nm]["lanes"][lid] = [float(corr[0]), float(corr[1]), 0.0, 0.0]
        print("[锚] %-6s %-3s → %s" % (nm, lid, ST[nm]["lanes"][lid]))

    # 2) 重描
    newQ = {}
    for key in RETRACE:
        lid, a, b = key.split("|")
        A = np.array(F.corridor_pt(a, lid), dtype=float)
        B = np.array(F.corridor_pt(b, lid), dtype=float)
        P, why = U.trace_seg2(lid, A, B)
        if P is None:
            print("[败] %s A*失败 %s" % (key, why))
            continue
        Q = FR.dedup(FR.rdp(P, RDP_EPS), DEDUP)
        Q = [[float(x), float(y)] for x, y in Q]
        Q[0] = [float(A[0]), float(A[1])]
        Q[-1] = [float(B[0]), float(B[1])]
        dm = depth_med(Q, lid, A, B)
        print("[描] %-18s %d点 带深中位=%.1f" % (key, len(Q), dm))
        newQ[key] = (Q, dm)

    # 3) 写入描线
    for key, (Q, dm) in newQ.items():
        DOC.setdefault("traced", {})[key] = [[round(x, 1), round(y, 1)] for x, y in Q]
        DOC["octi_off"] = sorted(set(DOC.get("octi_off") or []) | {key})

    # 4) 验收
    fails = []
    for key in RETRACE:
        if key not in newQ:
            fails.append("%s A*失败" % key)
            continue
        aft = U.measure(*key.split("|"))
        p90 = aft[1] if aft else 999.0
        b90 = base[key][1] if base[key] else 0.0
        dmed = newQ[key][1]
        ok = (dmed >= 8.0) and (p90 <= b90 + 1.0)
        print("[验] %-18s 带深%.1f p90 %.1f→%.1f  %s"
              % (key, dmed, b90, p90, "OK" if ok else "FAIL"))
        if not ok:
            fails.append(key)
    for k in all_segs:
        if k in RETRACE:
            continue
        aft = U.measure(*k.split("|"))
        p90 = aft[1] if aft else 999.0
        b90 = base[k][1] if base[k] else 0.0
        if p90 > b90 + 2.0:
            print("[验] 邻段 %-16s %.1f→%.1f FAIL" % (k, b90, p90))
            fails.append("邻段" + k)

    if fails:
        print("\n[还原] 失败项: %s" % fails)
        for (nm, lid), old in snap_lanes.items():
            if old:
                ST[nm]["lanes"][lid] = old
            else:
                ST[nm].get("lanes", {}).pop(lid, None)
        for k, old in snap_traced.items():
            if old is not None:
                DOC.setdefault("traced", {})[k] = old
            else:
                DOC.get("traced", {}).pop(k, None)
        DOC["octi_off"] = snap_oo
        print("[还原完成]")
    else:
        print("\n[全部通过]")
        try:
            import core.data_manager as CDM
            CDM.get_data_manager().save()
            print("[落盘] dm.save() 完成")
        except Exception as e:
            print("[落盘失败]", repr(e))


if __name__ == "__main__":
    main()
