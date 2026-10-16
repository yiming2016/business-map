# -*- coding: utf-8 -*-
"""★★ 让每一段线路**趴在官方底图的中心线上**（v2.6.64）。

## 为什么会有这个工具
用户原话：「我举例的线路根本没有完全贴合下面的底图」。
排查后发现之前用的量尺是**错的**：
  · "到最近同色像素的距离" ⇒ 只要还在 22px 宽的带子里就是 0，量不出"没居中"；
  · "距离变换中位数当半宽" ⇒ 带子的 D 中位数 = W/4（不是 W/2），
    于是"偏移"在**偏离中心 1/4 处**才归零 —— 也是错的。
**正尺**：对掩膜做距离变换 D，带子中心线处 D = W/2 = 2×中位数（中位 D 是 W/4）。
       某点的**偏离中心量 = 2×median(D[带内]) − D(该点)**，落在中心线上就是 0。

## 两类根因（都已实测确认）
  ① 段**没描线** ⇒ 站点直连 + 八向化，而官方是平滑的弧/L 形 ⇒ 形状根本对不上；
  ② 段有描线，但**端点（站点走廊落脚点）不在官方中心线上** ⇒ 整段平行偏。
  ⇒ 两条路的修法都是同一条：**在官方色掩膜上按 1/(D+1) 权重走最短路**（贴中心线），
     写进 `lines_doc["traced"]`，同时把该段加进 `lines_doc["octi_off"]`（不许八向化，
     否则重描的弧又会被拆成台阶）。

## 自检铁律
  ★ 改完必须用**真实渲染**再量一次（不是拿算式推），偏移没变小就**不写**。
  ★ 只写"改后确实更贴"的段，其余原样保留并在报告里列出。

用法：
    python tools/fix_fit_official.py              # 只扫描，出全图偏移报告
    python tools/fix_fit_official.py --apply      # 修 + 写入（先备份）
    python tools/fix_fit_official.py --line 12    # 只看某条线
"""
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_closing, distance_transform_edt, label
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))

import core.data_manager as CDM
CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"
from ui.map_view import build_line_points_ex, line_station_xy, traced_paths, octi_off_paths
from ui import metro_render as MR

import fix_retrace_from_official as FR          # 复用它的掩膜/最短路/自检

OFF = FR.OFF
COLORS = FR.COLORS
TOL = 48

MARGIN = 200.0        # 每段取块的边距（比 FR 的 300 略小，够用且快）
TRIM_END = 34.0       # 两端各掐掉多少 px 再量偏移（站点圆点/药丸会盖住官方线）
BAD_P90 = 3.0         # 判"明显没贴合"的阈值（px，场景单位 == 原图像素）
GOOD_GAIN = 1.5       # 改后偏移至少要降这么多 px 才值得写

dm = CDM.get_data_manager()
ST = dm.all_stations()
DOC = dm.lines_doc
LINES = DOC.get("lines") or []


def line_mask_stats(lid, A, B, margin=MARGIN):
    """按段建局部掩膜（闭运算去小断裂），返回 (D, x0, y0)。

    ★ 两个量尺教训（都是被放大图打脸后改的）：
      ① 不再选"最大连通域"： terminus/换乘区里选错 CC 会让整段 D=0 ⇒ 假报没贴合；
      ② 不再用"2×median(D) 当带半宽"：块里混进药丸/并行走廊时 median 被抬高
        ⇒ W2 虚高 14~22 ⇒ 又是假报。改用**逐点局部极大**（窗口内 D 的最大值
        = 该处带子的真实半宽），偏移 = 局部极大 − 该点 D，天然自适应。
    """
    x0 = max(0, int(min(A[0], B[0]) - margin))
    y0 = max(0, int(min(A[1], B[1]) - margin))
    x1 = min(8000, int(max(A[0], B[0]) + margin))
    y1 = min(8000, int(max(A[1], B[1]) + margin))
    if x1 - x0 < 20 or y1 - y0 < 20:
        return None
    rgb = (COLORS.get(lid) or {}).get("colors") or []
    if not rgb:
        return None
    c = rgb[0][0]
    blk = OFF[y0:y1, x0:x1]
    m = np.abs(blk - np.array(c, dtype=np.int16)).sum(axis=2) < TOL
    if m.sum() < 200:
        return None
    m = binary_closing(m, structure=np.ones((9, 9)))
    if m.sum() < 200:
        return None
    D = distance_transform_edt(m)
    return (D, x0, y0)


WIN_R = 20           # 局部极大窗口半径（带子半宽 ~11，窗口 41px 足够包住横截面）


def offsets(D, x0, y0, pts, win_r=WIN_R):
    """一串场景坐标点，返回"偏离官方带子中心线"的量（>0），出块记 None。

    偏移 = 窗口内 D 的最大值 − 该点的 D。点在中心线上 ⇒ 两者相等 ⇒ 0；
    点贴边 ⇒ D=0 而 max≈半宽 ⇒ 偏移≈半宽。
    """
    out = []
    H, W = D.shape
    for x, y in pts:
        xi, yi = int(round(x - x0)), int(round(y - y0))
        if xi < win_r or yi < win_r or xi >= W - win_r or yi >= H - win_r:
            out.append(None)
            continue
        loc = float(D[yi - win_r:yi + win_r + 1, xi - win_r:xi + win_r + 1].max())
        out.append(max(0.0, loc - float(D[yi, xi])))
    return out


def resample(P, step=6.0):
    if len(P) < 2:
        return np.asarray(P, dtype=float)
    out = []
    for i in range(len(P) - 1):
        (x0, y0), (x1, y1) = P[i], P[i + 1]
        L = float(np.hypot(x1 - x0, y1 - y0))
        n = max(1, int(np.ceil(L / step)))
        for k in range(n):
            t = k / n
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    out.append(P[-1])
    return np.asarray(out, dtype=float)


def trim(P, head=TRIM_END, tail=TRIM_END):
    """★ 必须先重采样再掐头去尾。

    踩过的坑：原版开头写 `if len(P) < 3: return P` —— 而"整线渲染后切出来"的段
    常常**只有 2 个点**（就是两个站点端点）。于是整段只量了两个端点，而站点处
    官方线被站点圆点/药丸盖住 ⇒ D=0 ⇒ 偏移恒等于带半宽 ⇒ 全图 374/419 段假报
    "没贴合"。探针 `_probe_fit_xcheck.py` 用独立方法一撞就露馅。
    """
    Q = resample(P, 6.0) if len(P) >= 2 else np.asarray(P, dtype=float)
    if len(Q) < 3:
        return Q
    acc = [0.0]
    for k in range(1, len(Q)):
        acc.append(acc[-1] + float(np.hypot(*(Q[k] - Q[k - 1]))))
    total = acc[-1]
    if total <= head + tail + 20:
        mid = Q[len(Q) // 3: max(1, 2 * len(Q) // 3)]
        return mid if len(mid) >= 2 else Q
    keep = [k for k in range(len(Q)) if head <= acc[k] <= total - tail]
    return Q[keep] if len(keep) >= 2 else Q


def stats(vals):
    v = np.asarray([x for x in vals if x is not None], dtype=float)
    if v.size == 0:
        return None
    return (float(np.percentile(v, 50)), float(np.percentile(v, 90)),
            float(v.max()), int(v.size))


def corridor_pt(nm, lid):
    s = ST[nm]
    return FR.corridor_xy(s, lid)


def drawn_polyline(lid, seq):
    pts, ebl = build_line_points_ex(lid, seq, ST)
    w = MR.octilinear_waypoints_tagged(pts, ebl)
    return [(float(p.x()), float(p.y())) for p, _ in w]


def slice_between(poly, A, B):
    ia = int(np.argmin([np.hypot(x - A[0], y - A[1]) for x, y in poly]))
    ib = int(np.argmin([np.hypot(x - B[0], y - B[1]) for x, y in poly]))
    if ia > ib:
        ia, ib = ib, ia
    seg = poly[ia:ib + 1]
    return seg if len(seg) >= 2 else [A, B]


def _local_max(D, x0, y0, pts, win_r=WIN_R):
    """每个采样点周围窗口里 D 的最大值（= 该处带子的真实半宽），出块记 None。"""
    out = []
    H, W = D.shape
    for x, y in pts:
        xi, yi = int(round(x - x0)), int(round(y - y0))
        if xi < win_r or yi < win_r or xi >= W - win_r or yi >= H - win_r:
            out.append(None)
            continue
        out.append(float(D[yi - win_r:yi + win_r + 1, xi - win_r:xi + win_r + 1].max()))
    return out


def main():
    args = sys.argv[1:]
    only = args[args.index("--line") + 1] if "--line" in args else None
    apply_ = "--apply" in args

    TR = traced_paths()
    OO = octi_off_paths()
    print("=" * 100)
    print("贴合体检：%s   （正尺 = 2×median(D[带内]) − D(点)；带子中心线处 = 0）"
          % ("**写入**" if apply_ else "只看不动"))
    print("=" * 100)
    print("%-4s %-22s %7s %6s %6s %6s  %-4s %-4s %s" %
          ("线", "段", "带半宽", "偏p50", "偏p90", "偏max", "描线", "免八", "判定"))

    todo, all_rows = [], []
    for L in LINES:
        lid = str(L.get("id"))
        if only and lid != only:
            continue
        seq = [n for n in (L.get("stations") or []) if n in ST]
        if len(seq) < 2:
            continue
        try:
            poly = drawn_polyline(lid, seq)
        except Exception as e:
            print("  [%s] 渲染失败 %r" % (lid, e))
            continue
        for i in range(len(seq) - 1):
            a, b = seq[i], seq[i + 1]
            key = "%s|%s|%s" % (lid, a, b)
            A, B = corridor_pt(a, lid), corridor_pt(b, lid)
            blk = line_mask_stats(lid, A, B)
            if blk is None:
                print("%-4s %-22s  %s" % (lid, "%s→%s" % (a, b), "掩膜不可信，跳过"))
                continue
            D, x0, y0 = blk
            pts_t = trim(slice_between(poly, A, B))
            vals = offsets(D, x0, y0, pts_t)
            st_ = stats(vals)
            if st_ is None:
                continue
            # 掩膜可信度：采样点附近窗口里的 D 最大值（= 局部带半宽）中位应在 6~20
            thick = float(np.median([v for v in _local_max(D, x0, y0, pts_t) if v is not None] or [0]))
            if thick < 6.0 or thick > 20.0:
                print("%-4s %-22s  %s（局部带宽中位 %.1f）" %
                      (lid, "%s→%s" % (a, b), "掩膜不可信，跳过", thick))
                continue
            p50, p90, mx, n = st_
            bad = p90 > BAD_P90
            all_rows.append((lid, a, b, key, thick, p50, p90, mx, bad))
            if bad:
                todo.append((lid, a, b, key, p50, p90, mx, thick))
            print("%-4s %-22s %7.1f %6.1f %6.1f %6.1f  %-4s %-4s %s" %
                  (lid, "%s→%s" % (a, b), thick, p50, p90, mx,
                   "有" if key in TR else "无", "是" if key in OO else "否",
                   "★明显没贴合" if bad else "ok"))

    print("-" * 100)
    nbad = sum(1 for r in all_rows if r[8])
    print("共测 %d 段，明显没贴合（偏p90 > %.1fpx）%d 段" % (len(all_rows), BAD_P90, nbad))
    if todo:
        print("\n需要重描的段：")
        for lid, a, b, key, p50, p90, mx, thick in sorted(todo, key=lambda r: -r[5]):
            print("   %-4s %-24s 偏 p50=%4.1f p90=%4.1f max=%5.1f" %
                  (lid, "%s→%s" % (a, b), p50, p90, mx))

    if not apply_:
        print("\n（没写入。确认后加 --apply）")
        return 0

    # ---------------- 写入 ----------------
    print("\n" + "=" * 100)
    print("开始重描…")
    changed, failed = {}, []
    for lid, a, b, key, p50, p90, mx, W2 in sorted(todo, key=lambda r: -r[6]):
        rgb = (COLORS.get(lid) or {}).get("colors") or []
        if not rgb:
            failed.append((key, "没色表"))
            continue
        A, B = corridor_pt(a, lid), corridor_pt(b, lid)
        P, why = FR.trace_seg(rgb[0][0], A, B)
        if P is None:
            failed.append((key, why))
            continue
        # ★ RDP 容差必须 **远小于** 要修的偏差（~11px）。用 FR.RDP_EPS=18 会把
        #   整条缓弧压回 2 点直线（实测 202 点 → 2 点，"改善 0.0px" 的 64 段全是它）。
        #   5px 弧形能留住；dedup(42) 保留防"折点扎堆"（<35px 会被回归判 FAIL）。
        Q = FR.dedup(FR.rdp(P, 5.0))
        if len(Q) < 2:
            failed.append((key, "简化后只剩 %d 点" % len(Q)))
            continue
        changed[key] = Q
    print("重描得到 %d 段，失败 %d 段" % (len(changed), len(failed)))
    for k, w in failed:
        print("   [放弃] %-26s %s" % (k, w))

    if not changed:
        print("没有可写入的段。")
        return 0

    # ★ 自检：把候选写进**内存**，重新渲染，用正尺再量一次；没变好就**还原**
    print("\n自检（真实渲染 + 正尺复量）…")

    def undo(key, had_tr, had_oo):
        """★ 还原这一段**改动前**的状态 —— 不是删除！

        踩过的坑：第一版写 `tr_.pop(key)` / 从 octi_off 里剔除。若这一段**本来就有**
        描线（上一轮工具写的、或用户手动描的），丢弃时会被连根拔掉 —— 实测
        apply#1 修好的段在 apply#2 丢弃时被清空，共误删 50 段描线
        （13|光明城|德雅路、5|前海湾|临海 等），渲染直接退回直线。
        """
        tr_ = DOC.setdefault("traced", {})
        if had_tr is not None:
            tr_[key] = had_tr
        else:
            tr_.pop(key, None)
        oo = set(DOC.get("octi_off") or [])
        if had_oo:
            oo.add(key)
        else:
            oo.discard(key)
        DOC["octi_off"] = sorted(oo)

    keep, drop = {}, []
    for key, Q in changed.items():
        lid, a, b = key.split("|")
        had_tr = (DOC.get("traced") or {}).get(key)
        had_oo = key in set(DOC.get("octi_off") or [])
        DOC.setdefault("traced", {})[key] = [[round(float(x), 1), round(float(y), 1)] for x, y in Q]
        # ★ 重描的段必须免八向化，否则弧又被拆台阶
        DOC["octi_off"] = sorted(set(DOC.get("octi_off") or []) | {key})
        seq = [n for n in next(L for L in LINES if str(L.get("id")) == lid)["stations"] if n in ST]
        try:
            poly2 = drawn_polyline(lid, seq)
        except Exception as e:
            drop.append((key, "重渲染失败 %r" % e))
            undo(key, had_tr, had_oo)
            continue
        A, B = corridor_pt(a, lid), corridor_pt(b, lid)
        blk = line_mask_stats(lid, A, B)
        if blk is None:
            drop.append((key, "掩膜不可信"))
            undo(key, had_tr, had_oo)
            continue
        D, x0, y0 = blk
        pts_t = trim(slice_between(poly2, A, B))
        st2 = stats(offsets(D, x0, y0, pts_t))
        if st2 is None:
            drop.append((key, "复量失败"))
            undo(key, had_tr, had_oo)
            continue
        before = next(r for r in all_rows if r[3] == key)
        gain = before[6] - st2[1]
        if gain >= GOOD_GAIN:
            keep[key] = Q
            print("   [留] %-26s p90 %5.1f → %5.1f  (−%.1f)" % (key, before[6], st2[1], gain))
        else:
            drop.append((key, "改善不足 %+.1fpx" % (st2[1] - before[6])))
            undo(key, had_tr, had_oo)

    print("\n自检结果：保留 %d 段，丢弃 %d 段" % (len(keep), len(drop)))
    for k, w in drop:
        print("   [丢] %-26s %s" % (k, w))

    if not keep:
        print("没有任何段通过自检，不写入。")
        return 0

    bak = DATA / ("lines.json.bak_fit_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(DATA / "lines.json", bak)
    tr = DOC.setdefault("traced", {})
    for k, Q in keep.items():
        tr[k] = [[round(float(x), 1), round(float(y), 1)] for x, y in Q]
    DOC["octi_off"] = sorted(set(DOC.get("octi_off") or []) | set(keep))
    (DATA / "lines.json").write_text(json.dumps(DOC, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    print("[备份] %s" % bak.name)
    print("[写入] traced 覆盖 %d 段（共 %d 段）；octi_off 共 %d 段"
          % (len(keep), len(tr), len(DOC["octi_off"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
