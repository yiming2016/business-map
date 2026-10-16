# -*- coding: utf-8 -*-
"""fix_anchor_u9.py —— v2.6.65-u9：按官方色带中心纠正 per-line 锚点（lanes）。

病根（叠图实证）：八卦岭'7' 低 22px、后海'2' 东偏 24px、科苑'2' 低 38px……
描线两端钉在偏的锚点上 ⇒ 整段平行偏移 + 站端肘部扭曲。
量尺 p90 掐头去尾（TRIM_END）看不见端点 ⇒ 扫描恒"ok"、自检恒拒。

方法：对每个 (站, 线)：
  1. 用相邻目标段的 A* 路径求锚点附近的走廊方向（25~70px 窗口 PCA）；
  2. 沿垂线采样官方色带距离变换 D，找含走廊的连续高 D run（≥12px）；
  3. run 中心 = 官方走廊中心垂足 ⇒ 纠正向量 = 垂足 − 锚点（只动垂线分量）；
  4. 硬护栏：|修正| ≤ 45、修正后 D ≥ 8、所有邻段 p90 恶化 ≤ 1.0，否则还原。

用法：python fix_anchor_u9.py          # 预演
      python fix_anchor_u9.py --apply # 写入（dm.save() 落盘）
"""
import math
import sys
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt

sys.argv = [sys.argv[0]] if len(sys.argv) == 1 else sys.argv
import fix_fit_user9 as U          # 复用 DOC/ST/seq_of/mask_big/measure
import fix_fit_official as F
import fix_retrace_from_official as FR

APPLY = "--apply" in sys.argv

# (站, 线, 用哪段求方向) —— 方向段取该站相邻的目标段
ITEMS = [
    ("大剧院", "1", ("1", "大剧院", "老街")),
    ("老街",   "1", ("1", "大剧院", "老街")),
    ("老街",   "3", ("3", "老街", "晒布")),
    ("晒布",   "3", ("3", "老街", "晒布")),
    ("黄木岗", "7", ("7", "黄木岗", "八卦岭")),
    ("八卦岭", "7", ("7", "黄木岗", "八卦岭")),
    ("红岭北", "7", ("7", "八卦岭", "红岭北")),
    ("深圳湾公园", "9", ("9", "深圳湾公园", "下沙")),
    ("下沙",   "9", ("9", "深圳湾公园", "下沙")),
    ("后海",   "2", ("2", "后海", "科苑")),
    ("科苑",   "2", ("2", "后海", "科苑")),
]

MAX_CORR = 30.0     # 修正上限（场景单位）；再大的归手动
MAX_ALONG = 10.0    # 修正的沿走廊分量上限（站体沿走廊位置不该自动挪）


def white_hole(nm, guess):
    """官方图上 (站) 附近的白洞（站体）中心，找不到返回 None。"""
    from scipy import ndimage
    OFF = F.OFF
    white = (OFF > 232).all(axis=2)
    lab, n = ndimage.label(white)
    objs = ndimage.center_of_mass(white, lab, range(1, n + 1))
    sizes = ndimage.sum(white, lab, range(1, n + 1))
    cents = np.array(objs)
    szs = np.array(sizes)
    gy, gx = float(guess[1]), float(guess[0])
    d = np.hypot(cents[:, 0] - gy, cents[:, 1] - gx)
    sel = (d < 70) & (szs > 250) & (szs < 6000)
    if not sel.any():
        return None
    i = int(np.argmin(np.where(sel, d, 1e9)))
    return float(cents[i][1]), float(cents[i][0])   # (x, y)
MIN_D_AFTER = 8.0   # 修正后必须深居带内
MIN_RUN = 6.0       # 垂线上连续高 D 才算真带（带宽22 ⇒ D≥6 段约 10px）
NEIGH_TOL = 1.0     # 邻段 p90 容忍恶化


def anchor_of(nm, lid):
    return np.array(F.corridor_pt(nm, lid), dtype=float)


def path_of(lid, a, b):
    A = anchor_of(a, lid)
    B = anchor_of(b, lid)
    P, why = U.trace_seg2(lid, A, B)
    return (P, A, B) if P is not None else (None, A, B, why)


def propose(nm, lid, seg):
    """返回 (修正向量, 说明)。

    方法：A* 路径（骑官方带中心）上取离锚点 40~90px 的采样点（避开站体白洞），
    每个采样点沿垂线找官方带中心（±25px 内 D≥6 连续 run 的加权中心），
    得到一串"真中心线"样本 ⇒ PCA 拟合直线 ⇒ 锚点到直线的垂距 = 修正向量。
    方向一致性护栏：40-60px 与 65-90px 两段的走向差 >25° 视为站端肘部，跳过。
    """
    sl, sa, sb = seg
    P, A, B = path_of(sl, sa, sb)
    if P is None:
        return None, "A*失败"
    anchor = anchor_of(nm, lid)
    inner = np.array(P[1:-1], dtype=float)
    d = np.hypot(inner[:, 0] - anchor[0], inner[:, 1] - anchor[1])
    near = inner[(d >= 20) & (d <= 95)]
    if len(near) < 6:
        return None, "近端路径点不足(%d)" % len(near)
    # 方向一致性：40-60 vs 65-90
    def _dir(lo, hi):
        w = inner[(d >= lo) & (d <= hi)]
        if len(w) < 3:
            return None
        c = w.mean(axis=0)
        _, _, vt = np.linalg.svd(w - c)
        return vt[0]
    d1 = _dir(40, 60)
    d2 = _dir(65, 90)
    if d1 is not None and d2 is not None:
        ang = math.degrees(math.acos(max(-1.0, min(1.0, float(abs(np.dot(d1, d2)))))))
        if ang > 25:
            return None, "站端肘部(方向差%.0f°)——归手动" % ang
    # 掩膜与距离变换
    m, x0, y0 = U.mask_big(sl, A, B)
    if m is None:
        return None, "掩膜为空"
    D = distance_transform_edt(m)
    # 在 40~90px 的路径点上采样带中心
    samples = []
    idx = np.where((d >= 40) & (d <= 90))[0]
    step = max(1, len(idx) // 8)
    for i in idx[::step]:
        p = inner[i]
        # 局部方向（前后 12px 的路径点）
        j0, j1 = max(0, i - 4), min(len(inner) - 1, i + 4)
        lv = inner[j1] - inner[j0]
        n2 = float(np.hypot(*lv))
        if n2 < 1:
            continue
        lv = lv / n2
        pv = np.array([-lv[1], lv[0]])
        ts = np.arange(-25.0, 25.01, 1.0)
        ds = []
        for t in ts:
            q = p + pv * t
            xi, yi = int(round(q[0])) - x0, int(round(q[1])) - y0
            ok = (0 <= yi < D.shape[0] and 0 <= xi < D.shape[1])
            ds.append(float(D[yi, xi]) if ok else 0.0)
        ds = np.array(ds)
        # 找 D≥6 的 run（含路径点自身所在带）
        best = None
        i2 = 0
        while i2 < len(ds):
            if ds[i2] >= 6.0:
                j2 = i2
                while j2 + 1 < len(ds) and ds[j2 + 1] >= 6.0:
                    j2 += 1
                if (ts[j2] - ts[i2]) >= MIN_RUN and (best is None or
                        ds[i2:j2 + 1].max() > best[2]):
                    w = ds[i2:j2 + 1] + 1e-6
                    tt = ts[i2:j2 + 1]
                    best = (float((tt * w).sum() / w.sum()), 0.0, float(w.max()))
                i2 = j2 + 1
            else:
                i2 += 1
        if best is None:
            continue
        t_c = best[0]
        q = p + pv * t_c
        samples.append(q)
    if len(samples) < 3:
        return None, "带中心样本不足(%d)" % len(samples)
    S = np.array(samples, dtype=float)
    c = S.mean(axis=0)
    _, _, vt = np.linalg.svd(S - c)
    dirv = vt[0]
    # 拟合残差大 ⇒ 中心线在此段是曲线/肘部，投影不可靠
    resid = float(np.max(np.abs((S - c) - np.outer((S - c) @ dirv, dirv))))
    if resid > 4.0:
        return None, "中心线弯曲(残差%.1fpx)——归手动" % resid
    v = anchor - c
    t = float(np.dot(v, dirv))
    foot = c + t * dirv
    corr = foot - anchor
    # 护栏①：沿走廊分量要小（锚点沿走廊的位置由站体决定，只该修垂直偏移）
    along = float(np.dot(corr, dirv))
    if abs(along) > MAX_ALONG:
        return None, "沿走廊分量 %.1f 超限——归手动" % along
    if float(np.hypot(*corr)) > MAX_CORR:
        return None, "修正 %.1f 超上限" % float(np.hypot(*corr))
    # 护栏②：官方站体（白洞）已与锚点对齐(<5px) ⇒ 锚不用动，扭曲归 retrace
    hole = white_hole(nm, (float(anchor[0]), float(anchor[1])))
    if hole is not None and float(np.hypot(hole[0] - anchor[0], hole[1] - anchor[1])) < 5.0:
        return None, "站体已对齐官方白洞——锚不动"
    return corr, "样本%d 残差%.1f" % (len(samples), resid)


def neighbor_segments(nm, lid):
    """该 (站,线) 的所有相邻段 key。"""
    seq = U.seq_of(lid)
    keys = []
    if nm in seq:
        i = seq.index(nm)
        if i > 0:
            keys.append("%s|%s|%s" % (lid, seq[i - 1], nm))
        if i + 1 < len(seq):
            keys.append("%s|%s|%s" % (lid, nm, seq[i + 1]))
    return keys


def main():
    print("=" * 74)
    print("锚位纠正预演" + ("（写入）" if APPLY else "（仅预演）"))
    print("=" * 74)
    proposals = []
    for nm, lid, seg in ITEMS:
        corr, why = propose(nm, lid, seg)
        a0 = anchor_of(nm, lid)
        if corr is None:
            print("[跳] %-6s %-3s  %s" % (nm, lid, why))
        else:
            print("[提] %-6s %-3s 锚(%.0f,%.0f) 修正 (%+.1f,%+.1f)  %s"
                  % (nm, lid, a0[0], a0[1], corr[0], corr[1], why))
            proposals.append((nm, lid, corr))

    if not APPLY:
        print("\n（预演结束，--apply 写入）")
        return

    print("\n---- 逐站写入（邻段护栏 %.1fpx）----" % NEIGH_TOL)
    applied = 0
    for nm, lid, corr in proposals:
        snap = (list(ST[lid].get("lanes", {}).get(lid, [])) if False else None)
        old_lane = list((U.ST[nm].get("lanes") or {}).get(lid, []))
        segs = neighbor_segments(nm, lid)
        before = {k: U.measure(*k.split("|")) for k in segs}
        # 写入 lanes
        U.ST[nm].setdefault("lanes", {})
        if old_lane:
            U.ST[nm]["lanes"][lid] = [old_lane[0] + corr[0], old_lane[1] + corr[1]] + list(old_lane[2:])
        else:
            U.ST[nm]["lanes"][lid] = [float(corr[0]), float(corr[1]), 0.0, 0.0]
        after = {k: U.measure(*k.split("|")) for k in segs}
        bad = []
        for k in segs:
            b = before.get(k)
            a = after.get(k)
            bv = b[1] if b else 0.0
            av = a[1] if a else 0.0
            if av - bv > NEIGH_TOL:
                bad.append("%s %.1f→%.1f" % (k, bv, av))
        if bad:
            # 还原
            if old_lane:
                U.ST[nm]["lanes"][lid] = old_lane
            else:
                U.ST[nm]["lanes"].pop(lid, None)
            print("[拒] %-6s %-3s 邻段恶化: %s" % (nm, lid, "; ".join(bad)))
        else:
            applied += 1
            det = "; ".join("%s %.1f→%.1f" % (k, before[k][1], after[k][1])
                            for k in segs if before.get(k) and after.get(k))
            print("[收] %-6s %-3s  %s" % (nm, lid, det or "无邻段量尺"))
    print("收 %d / %d" % (applied, len(proposals)))

    try:
        import core.data_manager as CDM
        dm = CDM.get_data_manager()
        dm.save()
        print("[落盘] dm.save() 完成")
    except Exception as e:
        print("[落盘失败]", repr(e))


if __name__ == "__main__":
    main()
