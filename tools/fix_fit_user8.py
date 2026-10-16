# -*- coding: utf-8 -*-
"""v2.6.64-u8：用户点名 8 段 + 全图扫描 p90>=4.5 的批量修复（桥接 A* 版）。

## 为什么这 8 段上一轮没修好（三个不同的病）
1. `FR.trace_seg` 掩膜只留**最大连通域** ⇒ 大换乘区/双线并行区选错 CC
   ⇒ 误报"站点离官方线太远"（12|国展|国展北、11|前海湾|南山）。
2. `fix_fit_official` 的"局部带宽中位"被噪点拖垮 ⇒ 误判"掩膜不可信"直接跳过
   ⇒ 从没被修过（5|临海|宝华、7|西丽湖|西丽）。
3. 短段（150~230px）A* 弧被 RDP+dedup 压回直线（2 号线四段）。

## 修法
掩膜 = closing 后**保留所有面积 ≥ 2500px 的 CC**（带子每 100px 长就有 2200px²，
噪点簇远小于此；并行带子/被站名分割的带子都保得住）。其余同 v2.6.64：
A* 贴中心线 → RDP(4) + dedup(36) → 写 traced + octi_off → **真实渲染自检**
（p90 须降 ≥1.5 才写，丢弃时**逐键还原**——v2.6.64 undo 误删 50 段的教训）。
"""
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_closing, distance_transform_edt, label
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

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

ST, DOC, LINES = F.ST, F.DOC, F.LINES
OFF = FR.OFF
TOL = 48
MIN_CC = 2500        # CC 面积下限（px²）
RDP_EPS = 4.0        # v2.6.64 教训：18 会把缓弧压回直线；4 保弧，dedup 负责去密
DEDUP = 36.0         # transfer_pair A1 判"折点扎堆 <35px" ⇒ 36 安全
GOOD_GAIN = 0.5      # v2.6.65：端点偏的段改善小（0.5~1px），只要不变差就收
MAX_END = 150.0
CLOSE_K = (9, 15)      # closing 梯度（连通性主要靠 bridge_cc 解决）

_u8 = ["2|深康|安托山", "2|安托山|侨香", "2|香梅北|景田", "2|景田|莲花西",
       "16|双龙|龙园", "16|新塘围|双龙", "13|东角头|歌剧院", "13|歌剧院|潮汐公园"]
_rest = [k.strip() for k in open(Path(__file__).parent / "targets_u8.txt", encoding="utf-8")
         if k.strip() and "|" in k]
TARGETS = _u8 + [k for k in _rest if k not in _u8]


def rgb_of(lid):
    e = FR.COLORS.get(lid)
    return e["colors"][0][0] if isinstance(e, dict) else e


def mask_big(lid, A, B, margin=300.0, k=9, min_cc=150):
    """closing(k) + 滤掉 <min_cc 的碎噪（保留大碎块——站点旁的带子可能被挖小）。
    返回 (m, x0, y0) 或 None。"""
    x0 = max(0, int(min(A[0], B[0]) - margin))
    y0 = max(0, int(min(A[1], B[1]) - margin))
    x1 = min(8000, int(max(A[0], B[0]) + margin))
    y1 = min(8000, int(max(A[1], B[1]) + margin))
    blk = OFF[y0:y1, x0:x1]
    m = np.abs(blk - np.array(rgb_of(lid), dtype=np.int16)).sum(axis=2) < TOL
    if int(m.sum()) < 200:
        return None
    m = binary_closing(m, structure=np.ones((k, k)))
    lab, n = label(m)
    if n > 1:
        sizes = np.bincount(lab.ravel())
        keep = np.zeros(sizes.shape, dtype=bool)
        keep[1:] = sizes[1:] >= min_cc
        m = keep[lab]
    if int(m.sum()) < 200:
        return None
    return (m, x0, y0)


def bridge_cc(g, lab, xs, ys, max_gap=90.0, bridge_cost=400.0):
    """★ build_graph 的图是**压缩图**（节点=掩膜像素，坐标在 xs/ys）。

    不同连通域之间 gap ≤ max_gap 的，最近点对加"桥边"（高代价）。
    站名文字/交叉线会把带子挖断成几块 ⇒ A* 图不连通（v2.6.59 在 trace_assist 里
    就有 BRIDGE=80/COST=400 的同类机制）。桥代价高 ⇒ A* 只在真断口才走桥。
    """
    n = g.shape[0]
    if n == 0 or ncc_max(lab) < 2:
        return g
    c_of = lab[ys, xs]                      # 每个节点的 CC 号
    pts_by_cc = {}
    for c in range(1, int(c_of.max()) + 1):
        idx = np.nonzero(c_of == c)[0]
        if idx.size == 0:
            continue
        if idx.size > 3000:
            idx = idx[:: int(np.ceil(idx.size / 3000))]
        pts_by_cc[c] = idx
    trees = {c: cKDTree(np.column_stack([xs[idx], ys[idx]]).astype(float))
             for c, idx in pts_by_cc.items()}
    from scipy.sparse import coo_matrix
    rows, cols, vals = [], [], []
    cs = sorted(pts_by_cc)
    for i, c1 in enumerate(cs):
        P1 = np.column_stack([xs[pts_by_cc[c1]], ys[pts_by_cc[c1]]]).astype(float)
        for c2 in cs[i + 1:]:
            d, j = trees[c2].query(P1, k=1)
            k1 = int(np.argmin(d))
            if d[k1] > max_gap:
                continue
            a = int(pts_by_cc[c1][k1])
            b = int(pts_by_cc[c2][j[k1]])
            w = bridge_cost * (d[k1] / 40.0)
            rows += [a, b]
            cols += [b, a]
            vals += [w, w]
    if not rows:
        return g
    return g + coo_matrix((vals, (rows, cols)), shape=g.shape)


def ncc_max(lab):
    return int(lab.max())


def trace_seg2(lid, A, B, margin=300.0):
    """= FR.trace_seg，但掩膜用 mask_big + closing 梯度（站名挖断带子时逐级加大）。"""
    last = None
    for k in CLOSE_K:
        r = mask_big(lid, A, B, margin, k=k)
        if r is None:
            last = "掩膜建不起来(k=%d)" % k
            continue
        m, x0, y0 = r
        D = distance_transform_edt(m)
        cost = 1.0 / (D + 1.0)
        g, (ys, xs) = FR.build_graph(m, cost)
        lab, _ = label(m)
        g = bridge_cc(g, lab, xs, ys)
        dA = np.hypot(xs + x0 - A[0], ys + y0 - A[1])
        dB = np.hypot(xs + x0 - B[0], ys + y0 - B[1])
        i0, i1 = int(dA.argmin()), int(dB.argmin())
        if dA[i0] > MAX_END or dB[i1] > MAX_END:
            last = "端点离官方带太远(%.0f/%.0f)——落脚点问题，需手动" % (dA[i0], dB[i1])
            continue
        dist, pred = dijkstra(g, indices=[i0], return_predecessors=True)
        pred, dist = pred[0], dist[0]
        if not np.isfinite(dist[i1]):
            last = "两点在掩膜上不连通(k=%d)" % k
            continue
        path, cur, guard = [], i1, 0
        while cur >= 0 and guard < 200000:
            path.append(cur)
            if cur == i0:
                break
            cur = pred[cur]
            guard += 1
        if not path or path[-1] != i0:
            last = "回溯失败"
            continue
        path = path[::-1]
        P = np.column_stack([xs[path] + x0, ys[path] + y0]).astype(float)
        P[0] = A
        P[-1] = B
        # ★ 路径自检：贴不住官方线说明走歪（描到别的结构上了），宁可放弃
        mm = np.column_stack([xs + x0, ys + y0]).astype(float)
        dd, _ = cKDTree(mm).query(P, k=1)
        if float(np.median(dd)) > 12.0:
            last = "路径没贴住官方线(中位%.1f)" % float(np.median(dd))
            continue
        return P, "ok(k=%d 原始%d点)" % (k, len(P))
    return None, (last or "未知失败")


def seq_of(lid):
    L = next(x for x in LINES if str(x.get("id")) == lid)
    return [n for n in (L.get("stations") or []) if n in ST]


def measure(lid, a, b):
    """真实渲染 + 新掩膜正尺复量。返回 (p50, p90, max) 或 None。"""
    try:
        A = F.corridor_pt(a, lid)
        B = F.corridor_pt(b, lid)
        poly = F.drawn_polyline(lid, seq_of(lid))
        seg = F.slice_between(poly, A, B)
        r = mask_big(lid, A, B)
        if r is None:
            return None
        m, x0, y0 = r
        D = distance_transform_edt(m)
        st = F.stats(F.offsets(D, x0, y0, F.trim(seg)))
        return st
    except Exception:
        return None


def main():
    apply_ = "--apply" in sys.argv
    print("定向修复 %d 段（%s）" % (len(TARGETS), "写入" if apply_ else "预演"))
    before_all = {}
    for key in TARGETS:
        lid, a, b = key.split("|")
        st = measure(lid, a, b)
        before_all[key] = st
        print("  修前 %-20s p50=%s p90=%s" % (
            key, "%.1f" % st[0] if st else "-", "%.1f" % st[1] if st else "-"))

    if not apply_:
        return 0

    bak = DATA / ("lines.json.bak_u8_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(DATA / "lines.json", bak)
    print("[备份] %s" % bak.name)

    kept, dropped = [], []
    for key in TARGETS:
        lid, a, b = key.split("|")
        A = F.corridor_pt(a, lid)
        B = F.corridor_pt(b, lid)
        # ★ v2.6.65：用户在段级菜单设的"凸弧/凹弧"存在 segment_shapes，渲染**优先于描线**
        #   （实测 7|西丽湖|西丽：描线数据是对的，cup 弧把它盖成斜弦 ⇒ 偏 11px）。
        #   这些段官方根本不是弧 ⇒ 删掉形状让描线接管（整份 lines.json 有备份可回滚）。
        had_shape = (DOC.get("segment_shapes") or {}).get(key)
        if had_shape:
            DOC.setdefault("segment_shapes", {}).pop(key, None)
        P, why = trace_seg2(lid, A, B)
        if P is None:
            if had_shape:
                DOC.setdefault("segment_shapes", {})[key] = had_shape
            dropped.append((key, why))
            print("  [跳] %-20s %s" % (key, why))
            continue
        Q = FR.dedup(FR.rdp(P, RDP_EPS), DEDUP)
        Q[0] = A
        Q[-1] = B
        had_tr = key in (DOC.get("traced") or {})
        had_oo = key in set(DOC.get("octi_off") or [])
        old_tr = (DOC.get("traced") or {}).get(key)
        DOC.setdefault("traced", {})[key] = [[round(float(x), 1), round(float(y), 1)] for x, y in Q]
        DOC["octi_off"] = sorted(set(DOC.get("octi_off") or []) | {key})
        after = measure(lid, a, b)
        bef = before_all[key]
        ok = (after is not None and bef is not None
              and bef[1] - after[1] >= GOOD_GAIN and after[1] <= bef[1] + 0.01)
        if ok:
            kept.append(key)
            print("  [留] %-20s p90 %.1f → %.1f  (%d 点)%s" % (
                key, bef[1], after[1], len(Q),
                "  [删弧 %s]" % had_shape if had_shape else ""))
        else:
            # ★ 逐键还原（v2.6.64 误删 50 段的教训：绝不 pop 有旧值的键）
            tr = DOC.setdefault("traced", {})
            if had_tr:
                tr[key] = old_tr
            else:
                tr.pop(key, None)
            if had_oo:
                DOC["octi_off"] = sorted(set(DOC.get("octi_off") or []) | {key})
            else:
                DOC["octi_off"] = [k for k in (DOC.get("octi_off") or []) if k != key]
            if had_shape:
                DOC.setdefault("segment_shapes", {})[key] = had_shape
            dropped.append((key, "自检改善不足 (%s → %s)" % (
                "%.1f" % bef[1] if bef else "?", "%.1f" % after[1] if after else "?")))
            print("  [丢] %-20s %s" % (key, dropped[-1][1]))

    print("-" * 70)
    print("留 %d 段 / 丢 %d 段" % (len(kept), len(dropped)))
    if not kept:
        print("没有任何段通过自检，不写盘。")
        return 0
    tmp = DATA / "lines.json.tmp"
    tmp.write_text(json.dumps(DOC, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(DATA / "lines.json")
    print("[写入] %s" % (DATA / "lines.json"))

    print("\n修后全部目标段复量：")
    for key in TARGETS:
        lid, a, b = key.split("|")
        st = measure(lid, a, b)
        b0 = before_all[key]
        print("  %-20s p90 %s → %s" % (key,
              "%.1f" % b0[1] if b0 else "-", "%.1f" % st[1] if st else "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
