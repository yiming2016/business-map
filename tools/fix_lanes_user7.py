# -*- coding: utf-8 -*-
"""v2.6.65 第二步：站点落脚点吸附到官方带中心线 + 邻段重描（组级原子自检）。

## 病根（第一步修完后仍剩 4 段的原因）
A* 描线被 RDP 压成直线是**对的**（官方带本来就直）——歪的是**站点落脚点**
（站体坐标 + lanes[线号] 偏移）本身不在官方带中心线上（偏 4~8px）。
描线两端被硬对齐到落脚点 ⇒ 整段平行偏/斜切，怎么描都贴不上。

## 修法（v2 第一版"只吸不描"被自检全拦 ⇒ 必须吸完重描）
端点在官方色距离变换 D 上**爬山**到带子中心线（≤32 步）；差值加进
lanes[线号] 的 dx/dy（站圆点/站名/站体一律不动；d[3]<3 ⇒ 无替身点副作用）。
然后**本段 + 相邻两段全部重描**（A* 从新落脚点走），组级自检：
本段 p90 必须降 ≥0.5，邻段不得升超 1px。任一不满足 ⇒ 整组还原。
"""
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import core.data_manager as CDM

CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"
import fix_fit_official as F
import fix_retrace_from_official as FR
import fix_fit_user7 as U

ST, DOC, LINES = U.ST, U.DOC, U.LINES
MAX_SNAP = 25.0
MIN_OFF = 3.5
NEIGH_TOL = 1.0
GAIN = 0.5

LANE_FIX = [
    ("5", "临海", "5|临海|宝华"),
    ("5", "宝华", "5|临海|宝华"),
    ("2", "水湾", "2|水湾|东角头"),
    ("7", "西丽湖", "7|西丽湖|西丽"),
]


def neighbors(lid, station):
    seq = U.seq_of(lid)
    if station not in seq:
        return []
    i = seq.index(station)
    out = []
    if i > 0:
        out.append("%s|%s|%s" % (lid, seq[i - 1], station))
    if i < len(seq) - 1:
        out.append("%s|%s|%s" % (lid, station, seq[i + 1]))
    return out


def endpoint_offset(lid, station):
    A = F.corridor_pt(station, lid)
    r = U.mask_big(lid, A, A, margin=200.0)
    if r is None:
        return None, None
    m, x0, y0 = r
    D = distance_transform_edt(m)
    v = F.offsets(D, x0, y0, [A], win_r=14)
    return (v[0] if v and v[0] is not None else None), (D, x0, y0)


def ridge(D, x0, y0, p, max_step=32):
    H, W = D.shape
    xi, yi = int(round(p[0] - x0)), int(round(p[1] - y0))
    if not (0 <= xi < W and 0 <= yi < H):
        return None
    if D[yi, xi] <= 0:
        found = False
        for rad in range(2, 26, 2):
            best = None
            for dy in range(-rad, rad + 1, 2):
                for dx in range(-rad, rad + 1, 2):
                    nj, ni = yi + dy, xi + dx
                    if 0 <= ni < W and 0 <= nj < H and D[nj, ni] > 0:
                        dd = dx * dx + dy * dy
                        if best is None or dd < best[0]:
                            best = (dd, ni, nj)
            if best:
                xi, yi = best[1], best[2]
                found = True
                break
        if not found:
            return None
    for _ in range(max_step):
        cur = D[yi, xi]
        bx, by = xi, yi
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                nj, ni = yi + dy, xi + dx
                if 0 <= ni < W and 0 <= nj < H and D[nj, ni] > cur:
                    cur = D[nj, ni]
                    bx, by = ni, nj
        if bx == xi and by == yi:
            break
        xi, yi = bx, by
    return (xi + x0, yi + y0)


def retrace(key):
    """重描一段（A* + RDP4 + dedup36 + octi_off），返回是否成功。"""
    lid, a, b = key.split("|")
    A = F.corridor_pt(a, lid)
    B = F.corridor_pt(b, lid)
    P, why = U.trace_seg2(lid, A, B)
    if P is None:
        return False, why
    Q = FR.dedup(FR.rdp(P, U.RDP_EPS), U.DEDUP)
    Q[0] = np.asarray(A)
    Q[-1] = np.asarray(B)
    DOC.setdefault("traced", {})[key] = [[round(float(x), 1), round(float(y), 1)] for x, y in Q]
    DOC["octi_off"] = sorted(set(DOC.get("octi_off") or []) | {key})
    return True, "%d点" % len(Q)


def main():
    apply_ = "--apply" in sys.argv
    print("落脚点吸附 + 邻段重描（%s）" % ("写入" if apply_ else "预演"))
    plan = []
    for lid, station, seg in LANE_FIX:
        off, blk = endpoint_offset(lid, station)
        if off is None or off < MIN_OFF:
            print("  %-4s %-6s 偏 %s —— 不吸" % (lid, station, "%.1f" % off if off else "?"))
            continue
        A = F.corridor_pt(station, lid)
        D, x0, y0 = blk
        T = ridge(D, x0, y0, A)
        if T is None:
            print("  %-4s %-6s 爬山失败" % (lid, station))
            continue
        dx, dy = T[0] - A[0], T[1] - A[1]
        if float(np.hypot(dx, dy)) > MAX_SNAP:
            print("  %-4s %-6s 偏 %.1f 超上限 —— 需手动" % (lid, station, float(np.hypot(dx, dy))))
            continue
        plan.append((lid, station, seg, float(dx), float(dy), float(off)))
        print("  %-4s %-6s 偏 %.1f ⇒ (%+.0f,%+.0f)" % (lid, station, off, dx, dy))

    if not apply_ or not plan:
        return 0

    bak = DATA / ("lines.json.bak_lanes2_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(DATA / "lines.json", bak)
    bak2 = DATA / ("stations.json.bak_lanes2_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(DATA / "stations.json", bak2)
    print("[备份] %s / %s" % (bak.name, bak2.name))

    # 按站分组（同一站只处理一次）
    seen = set()
    for lid, station, seg, dx, dy, off in plan:
        if (lid, station) in seen:
            continue
        seen.add((lid, station))
        st = ST[station]
        keys = sorted(set(neighbors(lid, station)) | {seg})
        # 快照
        snap_lanes = json.dumps(st.get("lanes") or {}, ensure_ascii=False)
        snap_tr = {k: (DOC.get("traced") or {}).get(k) for k in keys}
        snap_oo = {k: (k in set(DOC.get("octi_off") or [])) for k in keys}
        before = {k: U.measure(*k.split("|")) for k in keys}
        # 1) 改 lanes
        lanes = st.setdefault("lanes", {})
        ent = lanes.get(str(lid))
        if ent and len(ent) >= 2:
            ent[0] = round(float(ent[0]) + dx, 1)
            ent[1] = round(float(ent[1]) + dy, 1)
        else:
            lanes[str(lid)] = [round(dx, 1), round(dy, 1), 0.0, 0.0]
        # 2) 组内全部重描
        re_msgs = []
        for k in keys:
            okr, why = retrace(k)
            re_msgs.append("%s:%s" % (k, why))
        # 3) 组级自检
        ok_all, msgs = True, []
        for k in keys:
            after = U.measure(*k.split("|"))
            b0 = before[k]
            is_main = (k == seg)
            if after is None or b0 is None:
                continue
            if is_main and b0[1] - after[1] < GAIN:
                ok_all = False
                msgs.append("本段 %s 没变好 (%.1f→%.1f)" % (k, b0[1], after[1]))
            if not is_main and after[1] > b0[1] + NEIGH_TOL:
                ok_all = False
                msgs.append("邻段 %s 变差 (%.1f→%.1f)" % (k, b0[1], after[1]))
        if ok_all:
            print("  [留] %-4s %-6s  %s" % (lid, station, "  ".join(
                "%s %.1f→%.1f" % (k.split("|", 1)[1], before[k][1], U.measure(*k.split("|"))[1])
                for k in keys if before[k] and U.measure(*k.split("|")))))
        else:
            st["lanes"] = json.loads(snap_lanes)
            tr = DOC.setdefault("traced", {})
            oo = set(DOC.get("octi_off") or [])
            for k in keys:
                if snap_tr[k] is not None:
                    tr[k] = snap_tr[k]
                else:
                    tr.pop(k, None)
                if snap_oo[k]:
                    oo.add(k)
                else:
                    oo.discard(k)
            DOC["octi_off"] = sorted(oo)
            print("  [丢] %-4s %-6s  %s" % (lid, station, "; ".join(msgs)))

    sp = DATA / "stations.json"
    sd = json.loads(sp.read_text(encoding="utf-8"))
    for (lid, station) in seen:
        if station in (sd.get("stations") or {}):
            sd["stations"][station]["lanes"] = ST[station].get("lanes") or {}
    tmp = DATA / "stations.json.tmp"
    tmp.write_text(json.dumps(sd, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(sp)
    tmp2 = DATA / "lines.json.tmp"
    tmp2.write_text(json.dumps(DOC, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp2.replace(DATA / "lines.json")
    print("[写入] stations.json + lines.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
