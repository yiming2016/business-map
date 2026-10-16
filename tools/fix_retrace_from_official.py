# -*- coding: utf-8 -*-
"""★★ 修「完全没按官方走」的正解：**重建每一段的走法**，站点一个都不动。

根因（2026-10-01 画图定案）：官方图在站与站之间是**带拐弯的走法**（横→竖的 L 形、
45° 斜线），而我的是**两站直连** ⇒ 该拐的地方没拐，中段就切出去了（11号线
红树湾南→车公庙 差一个直角，中段偏 229px）。这也解释了八向合规只有 43%。

做法：在**官方原图该线的颜色掩膜**上做一次最短路，把官方那条线走一遍，写进
`lines_doc["traced"]`（渲染本来就优先用它，且会校验两端贴不贴站点）。

★ 两个关键点（不然路径会画歪）：
  ① 边权用 **1/(距离变换+1)** ⇒ 线宽 30px 的带子里，走路会**贴着中心线**而不是贴边；
  ② 首尾**强制改成两个站的精确坐标** ⇒ `_traced_fresh()` 才认（容差 90px）。

用法：
    python tools/fix_retrace_from_official.py --line 11          # 只看不动
    python tools/fix_retrace_from_official.py --line 11 --apply  # 写入（先备份）
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
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"

LINES_F = DATA / "lines.json"
ST_F = DATA / "stations.json"
doc = json.loads(LINES_F.read_text(encoding="utf-8"))
LINES = doc["lines"]
ST = json.loads(ST_F.read_text(encoding="utf-8"))["stations"]
COLORS = json.loads((ROOT / "_tmp_official_colors.json").read_text(encoding="utf-8"))
OFF = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)

NEI = [(dy, dx, (1.414 if dy and dx else 1.0))
       for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy or dx)]

MARGIN = 300.0      # 段两端往外扩多少去找官方线（要够大，弯道才包得住）
TOL = 48            # 颜色容差
MAX_END = 150.0     # 站点离官方线超过这个 ⇒ 这段不敢描
RDP_EPS = 18.0      # 路径简化容差（px）★ 太小会留下一堆抖动点，
                    # 渲染时两个折点只隔十几 px ⇒ 判"折点扎堆"


def build_graph(m, cost):
    """把掩膜像素建成 8 邻域图（向量化，避免 Python 逐点循环）"""
    H, W = m.shape
    ys, xs = np.nonzero(m)
    n = len(ys)
    key = ys * W + xs
    order = np.argsort(key)
    skey = key[order]
    rows, cols, vals = [], [], []
    for dy, dx, w in NEI:
        ny, nx = ys + dy, xs + dx
        ok = (ny >= 0) & (ny < H) & (nx >= 0) & (nx < W)
        nk = np.where(ok, ny * W + nx, -1)
        j = np.clip(np.searchsorted(skey, nk), 0, n - 1)
        hit = ok & (skey[j] == nk)
        if not hit.any():
            continue
        ii = np.arange(n)[hit]
        rows.append(ii)
        cols.append(order[j[hit]])
        vals.append(w * 0.5 * (cost[ys[hit], xs[hit]] + cost[ny[hit], nx[hit]]))
    g = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                   shape=(n, n)).tocsr()
    return g, (ys, xs)


def rdp(P, eps):
    """Ramer-Douglas-Peucker：把逐像素路径压成几个点（拐点一定要留住）"""
    if len(P) < 3:
        return P
    keep = np.zeros(len(P), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(P) - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        a, b = P[i0], P[i1]
        ab = b - a
        L2 = float(ab @ ab)
        mid = P[i0 + 1:i1]
        if L2 < 1e-9:
            d = np.linalg.norm(mid - a, axis=1)
        else:
            t = np.clip(((mid - a) @ ab) / L2, 0, 1)
            d = np.linalg.norm(mid - (a + t[:, None] * ab), axis=1)
        if d.size == 0:
            continue
        j = int(np.argmax(d)) + i0 + 1
        if d.max() > eps:
            keep[j] = True
            stack.append((i0, j))
            stack.append((j, i1))
    return P[keep]


def dedup(P, min_d=42.0):
    """★ 去掉挨得太近的点：端点要硬对齐站点，很容易造出 0.5px 的"零长度边"，
      渲染时就是 180° 急折。★ 阈值要 >35px：`_chk_transfer_pair`
      判"两个折点扎堆"的线就是 35px，实测 14px 会挂、42px 才过。
    """
    if len(P) < 2:
        return P
    out = [P[0]]
    for p in P[1:-1]:
        if float(np.hypot(*(p - out[-1]))) >= min_d:
            out.append(p)
    last = P[-1]
    if len(out) == 1 or float(np.hypot(*(last - out[-1]))) >= min_d:
        out.append(last)
    else:
        out[-1] = last          # 太近就顶掉前一个，绝不留零长度边
    return np.array(out)


def corridor_xy(st, lid):
    """★ v2.6.59：描线的两端必须是**渲染时真正画出来的那个点**，即
       「站体坐标(alt_bodies) + 本线走廊偏移(lanes[线号])」。
       只写站中心 ⇒ 渲染时起点是走廊点，路径首点却落在站中心 ⇒
       中间凭空多出一条几十像素的"斜插边"，端点跟着一个 100°+ 的急折
       （实测 7号线 黄木岗→八卦岭）。
    """
    x, y = float(st.get("x", 0)), float(st.get("y", 0))
    for b in (st.get("alt_bodies") or []):
        if str(b.get("line") or "") == str(lid):
            try:
                x, y = float(b["x"]), float(b["y"])
            except (KeyError, TypeError, ValueError):
                break
    d = (st.get("lanes") or {}).get(str(lid))
    if d:
        try:
            x, y = x + float(d[0]), y + float(d[1])
        except (IndexError, TypeError, ValueError):
            pass
    return x, y


def trace_seg(rgb, A, B):
    """在官方色掩膜上走一次最短路，返回场景坐标点列（首尾 = 两站）"""
    x0 = max(0, int(min(A[0], B[0]) - MARGIN))
    y0 = max(0, int(min(A[1], B[1]) - MARGIN))
    x1 = min(8000, int(max(A[0], B[0]) + MARGIN))
    y1 = min(8000, int(max(A[1], B[1]) + MARGIN))
    if x1 - x0 < 10 or y1 - y0 < 10:
        return None, "区域太小"
    blk = OFF[y0:y1, x0:x1]
    m = np.abs(blk - np.array(rgb, dtype=np.int16)).sum(axis=2) < TOL
    if m.sum() < 200:
        return None, "附近没有这个颜色的像素(%d)" % int(m.sum())

    # ★ 站点中心往往落在白底上（实测红树湾南/车公庙处官方图是纯白），
    #   而且掩膜混着一堆小噪点 ⇒ 先闭运算补断裂，再只留最大连通域（那条线本体）。
    m = binary_closing(m, structure=np.ones((9, 9)))
    lab, ncomp = label(m)
    if ncomp > 1:
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        m = (lab == int(sizes.argmax()))
    if m.sum() < 200:
        return None, "清掉噪点后没剩多少像素(%d)" % int(m.sum())
    D = distance_transform_edt(m)
    cost = 1.0 / (D + 1.0)          # ★ 中心线代价低 ⇒ 走路贴中心不贴边
    g, (ys, xs) = build_graph(m, cost)
    dA = np.hypot(xs + x0 - A[0], ys + y0 - A[1])
    dB = np.hypot(xs + x0 - B[0], ys + y0 - B[1])
    i0, i1 = int(dA.argmin()), int(dB.argmin())
    if dA[i0] > MAX_END or dB[i1] > MAX_END:
        return None, "站点离官方线太远(%.0f/%.0f)" % (dA[i0], dB[i1])
    dist, pred = dijkstra(g, indices=[i0], return_predecessors=True)
    pred, dist = pred[0], dist[0]
    if not np.isfinite(dist[i1]):
        return None, "两点在这条线的像素上不连通"
    path, cur, guard = [], i1, 0
    while cur >= 0 and guard < 100000:
        path.append(cur)
        if cur == i0:
            break
        cur = pred[cur]
        guard += 1
    if not path or path[-1] != i0:
        return None, "回溯失败"
    path = path[::-1]
    P = np.column_stack([xs[path] + x0, ys[path] + y0]).astype(float)
    P[0] = A                        # ★ 首尾硬对齐站点，_traced_fresh 才认
    P[-1] = B
    # ★ 自检：这条路径本身贴不贴官方线（贴不住说明走歪了，不如不写）
    mm = np.column_stack([xs + x0, ys + y0]).astype(float)
    dd, _ = cKDTree(mm).query(P, k=1)
    med, mx = float(np.median(dd)), float(dd.max())
    # ★ 防描错：这段路径自己都没贴住官方线，说明走歪了（多半描到别的线上去了），
    #   宁可不写，也不要写一条错的路径进去。
    if med > 12.0:
        return None, "★路径没贴住官方线(中位%.1f)，放弃" % med
    return P, "ok 原始%3d点 贴线 中位%.1f/最大%.1f" % (len(P), med, mx)


def main():
    args = sys.argv[1:]
    lid = None
    if "--line" in args:
        lid = args[args.index("--line") + 1]
    apply_ = "--apply" in args
    if lid is None:
        print("用法: python tools/fix_retrace_from_official.py --line 11 [--apply]")
        return 2

    l = next((x for x in LINES if str(x.get("id")) == lid), None)
    if l is None:
        print("没有这条线：%s" % lid)
        return 2
    cols = (COLORS.get(lid) or {}).get("colors") or []
    if not cols:
        print("没有采到官方色：%s" % lid)
        return 2
    rgb = cols[0][0]
    seq = [s for s in (l.get("stations") or []) if s in ST and ST[s].get("x") is not None]

    print("=" * 88)
    print("重建走法：%s（官方色 %s）  %s" % (l.get("name") or lid, rgb,
                                        "**写入**" if apply_ else "只看不动"))
    print("=" * 88)
    traced = doc.setdefault("traced", {})
    out, skipped = {}, 0
    for i in range(len(seq) - 1):
        a, b = seq[i], seq[i + 1]
        va, vb = ST[a], ST[b]
        P, why = trace_seg(rgb, corridor_xy(va, lid), corridor_xy(vb, lid))
        key = "%s|%s|%s" % (lid, a, b)
        if P is None:
            skipped += 1
            print("  [跳过] %-22s %s" % ("%s→%s" % (a, b), why))
            continue
        Q = dedup(rdp(P, RDP_EPS))
        if len(Q) < 2:
            skipped += 1
            print("  [跳过] %-22s 简化后只剩 %d 点" % ("%s→%s" % (a, b), len(Q)))
            continue
        out[key] = Q
        span = float(np.hypot(vb["x"] - va["x"], vb["y"] - va["y"]))
        dev = 0.0
        for k in range(len(P) - 1):
            pass
        print("  [OK]   %-22s 段长%5.0f  %s → 简化%2d点"
              % ("%s→%s" % (a, b), span, why, len(Q)))

    print("-" * 88)
    print("可重建 %d 段 / 跳过 %d 段（共 %d 段）" % (len(out), skipped, len(seq) - 1))
    if not apply_:
        print("（没写入。确认后加 --apply）")
        return 0

    bak = DATA / ("lines.json.bak_retrace_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(LINES_F, bak)
    for k, Q in out.items():
        traced[k] = [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in Q]
    LINES_F.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[备份] %s" % bak.name)
    print("[写入] traced 新增/覆盖 %d 段（该表现在共 %d 段）" % (len(out), len(traced)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
