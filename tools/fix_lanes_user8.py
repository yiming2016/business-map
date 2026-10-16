# -*- coding: utf-8 -*-
"""v2.6.64-u8b：解析式落脚点（lanes 锚点）修正。

## 病根（上一轮 fix_lanes_user7 爬山法全军覆没之后的重做）
批量描线后仍偏的段，A* 都能走通、官方线本身是直的 —— 偏的是**两端锚点**：
站圆点/lanes 锚点整体偏出官方走廊 8~11px，描线两端被钉死在偏的锚点上，
怎么描都偏（复现：安托山→侨香 A* 121 点经 RDP 只剩 2 点直线，p90 纹丝不动）。

## 修法（解析，不是爬山）
1. A* 描出官方中心线 P（内部点在官方线上）。
2. 端点偏移向量 v = P 内部点里离锚点最近的点 − 锚点（|v|≤20 才可信）。
3. lanes[线号] 前两位 += v（已有 lanes 保 d[2]/d[3]；没有的新建 [vx,vy,0,0]，
   d[3]=0 <3 ⇒ 不产生替身点，普通站安全）。
4. 硬自检：目标段 p90 降 ≥0.5，且**该锚点上所有邻段** p90 升幅 ≤0.5；
   任一不满足 ⇒ 整键还原。上一轮的教训（宝华邻段 0.7→10.3）就拦在这。
"""
import copy
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import core.data_manager as CDM

CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"
import fix_fit_official as F
import fix_fit_user8 as U
import fix_retrace_from_official as FR

ST, DOC, LINES = F.ST, F.DOC, F.LINES
VMAX = 20.0
GAIN_NEED = 0.5
NEIGH_TOL = 0.8   # 邻段容忍：0.5px 恰好卡边界（实测安托山 +0.50 被拒），
                  # 0.8 仍远小于可见门槛（带宽 22px，量尺噪声 ±0.5）

# 修完描线后仍 p90>=6 的段（fix_fit_user8 修后复量表）+ 用户点名 4 段
TARGETS = [
    "2|深康|安托山", "2|安托山|侨香", "2|香梅北|景田", "16|新塘围|双龙",
    "9|高新南|红树湾南", "9|南山书城|深大南", "5|湖贝|东门", "1|竹子林|车公庙",
    "5|布吉|百鸽笼", "16|坪环|坪山围", "9|人民南|向西村", "13|潮汐公园|深圳湾口岸",
    "6|红山|深圳北站", "11|福星|华强南", "9|下梅林|梅村", "1|宝安中心|新安",
    "1|大剧院|老街", "6|科学公园|光明", "6|元芬|上芬", "14|岗厦北|黄木岗",
    "14|黄木岗|罗湖北", "7|车公庙|上沙", "9|粤海门|高新南", "3|福田|少年宫",
    "5|黄贝岭|湖贝", "5|深圳北站|民治", "3|老街|晒布", "13|深圳湾口岸|人才公园",
    "9|深圳湾公园|下沙", "2|水湾|东角头", "7|华强南|华强北",
    "2|科苑|红树湾", "2|莲花西|福田", "3|购物公园|福田", "1|车公庙|香蜜湖",
]


def seq_of(lid):
    L = next(x for x in LINES if str(x.get("id")) == lid)
    return [n for n in (L.get("stations") or []) if n in ST]


def incident_keys(station, lid):
    """(station, lid) 锚点上挂的所有段键（按线路站序）。"""
    seq = seq_of(lid)
    out = []
    if station not in seq:
        return out
    i = seq.index(station)
    if i > 0:
        out.append("%s|%s|%s" % (lid, seq[i - 1], station))
    if i + 1 < len(seq):
        out.append("%s|%s|%s" % (lid, station, seq[i + 1]))
    return out


def end_offset(lid, a, b, which):
    """端点偏移向量 v：把锚点平移到官方中心线上。

    ★ 不能用"离锚点最近的 A* 内部点"——路径两端被钉在锚点上，最近点被
      钉死偏置（实测安托山算出 (16,-10.3)，真值是 (0,-19)）。
    正确做法：取 A* 内部点里**离锚点 30~90px** 的那一段（已在带中心，
    D 中位=11 验证过），PCA 拟合直线，v = 锚点到该直线的垂距向量。
    """
    A = F.corridor_pt(a, lid)
    B = F.corridor_pt(b, lid)
    P, why = U.trace_seg2(lid, A, B)
    if P is None or len(P) < 8:
        return None
    anchor = np.array(A if which == "A" else B, dtype=float)
    inner = np.asarray(P[1:-1], dtype=float)
    d = np.hypot(inner[:, 0] - anchor[0], inner[:, 1] - anchor[1])
    sel = inner[(d > 30) & (d < 90)]
    if len(sel) < 5:
        return None
    mean = sel.mean(axis=0)
    c = sel - mean
    cov = c.T @ c
    w, vec = np.linalg.eigh(cov)
    direction = vec[:, -1]                     # 主方向
    n = np.array([-direction[1], direction[0]])  # 法向
    v = float((mean - anchor) @ n) * n         # 垂距向量（把锚点挪到拟合线上）
    if float(np.hypot(v[0], v[1])) > VMAX:
        return None
    if float(np.hypot(v[0], v[1])) < 1.0:
        return None
    return v


def apply_lane(station, lid, v, snapshot):
    """把 v 加进 lanes[lid] 前两位；先记快照。"""
    st = ST[station]
    key = "lanes[%s]" % lid
    snapshot[(station, lid)] = copy.deepcopy((st.get("lanes") or {}).get(lid))
    lanes = st.setdefault("lanes", {})
    old = lanes.get(lid)
    if old and len(old) >= 2:
        lanes[lid] = [round(float(old[0]) + float(v[0]), 1),
                      round(float(old[1]) + float(v[1]), 1),
                      float(old[2]) if len(old) > 2 else 0.0,
                      float(old[3]) if len(old) > 3 else 0.0]
    else:
        lanes[lid] = [round(float(v[0]), 1), round(float(v[1]), 1), 0.0, 0.0]
    return key


def restore(snapshot):
    for (station, lid), old in snapshot.items():
        st = ST[station]
        lanes = st.get("lanes") or {}
        if old is None:
            lanes.pop(lid, None)
            if not lanes and "lanes" in st:
                del st["lanes"]
        else:
            st.setdefault("lanes", {})[lid] = old


def main():
    apply_ = "--apply" in sys.argv
    print("解析式落脚点修正，%d 段（%s）" % (len(TARGETS), "写入" if apply_ else "预演"))
    accepted, rejected = [], []
    all_snaps = {}
    for key in TARGETS:
        lid, a, b = key.split("|")
        st0 = U.measure(lid, a, b)
        if st0 is None:
            continue
        fixed = False
        for which, nm in (("A", a), ("B", b)):
            v = end_offset(lid, a, b, which)
            if v is None:
                print("  [--] %-18s 端%s 偏移向量不可信(A*失败或|v|>%d)" % (key, which, VMAX))
                continue
            snap = {}
            apply_lane(nm, lid, v, snap)
            keys = [k for k in incident_keys(nm, lid) if k != key]
            after_t = U.measure(lid, a, b)
            ok = (after_t is not None and st0[1] - after_t[1] >= GAIN_NEED)
            if not ok:
                print("  [--] %-18s 端%s v=(%.1f,%.1f) 目标段自身改善不足 (%s → %s)"
                      % (key, which, v[0], v[1], "%.1f" % st0[1],
                         "%.1f" % after_t[1] if after_t else "?"))
            neigh = []
            if ok:
                for k in keys:
                    l2, x, y = k.split("|")
                    m2 = U.measure(l2, x, y)
                    if m2 is None:
                        continue
                    m1 = None
                    neigh.append((k, m2[1]))
            # 邻段要和"动之前"比：先记录动前值
            if ok and neigh:
                restore(snap)
                before = {}
                for k in keys:
                    l2, x, y = k.split("|")
                    m1 = U.measure(l2, x, y)
                    if m1 is not None:
                        before[k] = m1[1]
                apply_lane(nm, lid, v, snap)   # 重新应用（同一个 v，快照会覆盖为同值）
                worst = []
                for k, b1 in before.items():
                    l2, x, y = k.split("|")
                    m2 = U.measure(l2, x, y)
                    if m2 is not None and m2[1] - b1 > NEIGH_TOL:
                        worst.append("%s +%.1f" % (k, m2[1] - b1))
                ok = not worst
                if not ok:
                    print("  [拒] %-18s 端%s v=(%.1f,%.1f) 邻段恶化: %s"
                          % (key, which, v[0], v[1], "; ".join(worst)))
            if ok:
                all_snaps.update(snap)
                accepted.append((key, which, nm, float(v[0]), float(v[1]),
                                 st0[1], after_t[1]))
                print("  [收] %-18s 端%s %s v=(%.1f,%.1f) 目标p90 %.1f→%.1f"
                      % (key, which, nm, v[0], v[1], st0[1], after_t[1]))
                fixed = True
                break
            else:
                restore(snap)
        if not fixed:
            if key not in [x[0] for x in rejected]:
                rejected.append((key, "两端无可收的锚点修正"))

    print("-" * 70)
    print("收 %d 个锚点 / 段 %d" % (len(accepted), len(TARGETS)))
    if not apply_ or not accepted:
        restore(all_snaps)
        print("预演结束，未写盘。")
        return 0

    bak = DATA / ("stations.json.bak_lanes8_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(DATA / "stations.json", bak)
    print("[备份] %s" % bak.name)
    # lanes 改动在 ST（dm 活引用）里，dm.save() 一并原子落盘 stations+lines
    dm2 = CDM.get_data_manager()
    dm2.save()
    print("[落盘] dm.save() 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
