"""
tools/rederive_order.py
================================
拿原图的线路颜色当"铁轨"，重新推导每条线路的站序。

原理：
  1. 对每条线路，按官方颜色从原图抠出一张"掩膜"（线是彩色的，很好抠）；
  2. 把掩膜膨胀 10 像素，得到"线路走廊"；
  3. 任意两站之间，沿"横/竖/45°"的走法取样，统计有多少比例的取样点落在走廊里
     —— 这就是这两站之间"有没有线路连着"的可信度；
  4. 有了可信度，就把"乱连"的边排除掉，只允许沿着走廊连线；
  5. 在剩下的图里找一条经过所有站点的最短路径（最近邻多起点 + 2-opt + Or-opt）。

这样得到的站序，是"跟着原图的线走"排出来的，而不是凭坐标猜的。

用法：
    python tools/rederive_order.py             # 只看报告
    python tools/rederive_order.py --apply     # 写回 lines.json（自动备份）
"""

import json
import math
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SRC = Path(__file__).resolve().parent.parent
APPLY = "--apply" in sys.argv

LEGEND = {
    "1": (0x00, 0xB0, 0x52), "2": (0xBA, 0x57, 0x00), "3": (0x00, 0xA6, 0xDE),
    "4": (0xD4, 0x2E, 0x12), "5": (0x9E, 0x4D, 0xAB), "6": (0x00, 0xC4, 0xB5),
    "6支": (0x00, 0x8A, 0x80), "7": (0x00, 0x33, 0xAB), "8": (0xBA, 0x57, 0x00),
    "9": (0x8A, 0x6B, 0x70), "10": (0xFC, 0x6C, 0x97), "11": (0x6B, 0x1C, 0x40),
    "12": (0xA8, 0x91, 0xB0), "13": (0xD4, 0x85, 0x00), "14": (0xED, 0xCC, 0x61),
    "16": (0x40, 0x12, 0xA6), "20": (0x99, 0xDB, 0xDE),
}
# 这些线路在原图里颜色相同，用同一张掩膜
COLOR_KEY = {"8": "2", "6支": "6支"}     # 8 号线与 2 号线同色（贯通运营）

TOL = 24              # 抠色容差（原图是无损 PNG，颜色很准）
DILATE = 11           # 走廊半宽（像素）
OK_COVER = 0.55       # 超过这个覆盖率才算"这两站之间有线路连着"
LONG_EDGE = 4.0       # 覆盖率不足时的额外代价倍数


def load_masks():
    img = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)
    out = {}
    for lid, c in LEGEND.items():
        key = COLOR_KEY.get(lid, lid)
        if key in out:
            continue
        d = np.abs(img - np.array(c, dtype=np.int16)).max(axis=2)
        m = d <= TOL
        if m.sum() == 0:
            print(f"  [!] {lid} 号线没有抠到任何像素")
            continue
        out[key] = ndimage.binary_dilation(m, iterations=DILATE)
        print(f"  线路 {key}: 原始像素 {int(m.sum())}, 走廊像素 {int(out[key].sum())}")
    del img
    return out


def route_samples(a, b, tol=0.16, tol_px=30.0):
    """按"横/竖/45°"的走法，返回 a→b 路径上的取样点（与渲染逻辑保持一致）。"""
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    adx, ady = abs(dx), abs(dy)
    big = max(adx, ady)
    pts = None
    if adx < 1e-6 or ady < 1e-6 or min(adx, ady) < tol_px \
            or abs(adx - ady) <= big * tol:
        pts = [(ax, ay), (bx, by)]
    else:
        m = min(adx, ady)
        mid = (ax + (m if dx > 0 else -m), ay + (m if dy > 0 else -m))
        pts = [(ax, ay), mid, (bx, by)]

    out = []
    for i in range(1, len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        seg = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        n = max(6, int(seg / 14))
        k = np.linspace(0.10, 0.90, n)
        out.append((x0 + (x1 - x0) * k, y0 + (y1 - y0) * k))
    xs = np.concatenate([o[0] for o in out])
    ys = np.concatenate([o[1] for o in out])
    return xs, ys


def cover(mask, a, b):
    xs, ys = route_samples(a, b)
    xi = np.clip(xs.astype(int), 0, mask.shape[1] - 1)
    yi = np.clip(ys.astype(int), 0, mask.shape[0] - 1)
    return float(mask[yi, xi].mean())


def solve_path(n, cost, forbid):
    """多起点最近邻 + 2-opt + Or-opt，求经过所有点的最短路径。"""
    import random
    rng = random.Random(20260913)

    def path_cost(p):
        return sum(cost[p[i]][p[i + 1]] for i in range(len(p) - 1))

    def nn(start):
        unv = set(range(n)); unv.discard(start)
        p = [start]
        while unv:
            cur = p[-1]
            nxt = min(unv, key=lambda j: cost[cur][j] if not forbid[cur][j] else 1e12)
            p.append(nxt); unv.discard(nxt)
        return p

    def two_opt(p):
        improved = True
        while improved:
            improved = False
            for i in range(len(p) - 2):
                for j in range(i + 2, len(p)):
                    if j - i == 1:
                        continue
                    a, b = p[i], p[i + 1]
                    c, d = p[j], p[j + 1] if j + 1 < len(p) else None
                    if forbid[a][b] or (d is not None and forbid[c][d]):
                        continue
                    old = cost[a][b] + (cost[c][d] if d is not None else 0)
                    new = cost[a][c] + (cost[b][d] if d is not None else 0)
                    if new < old - 1e-6 and not forbid[a][c] \
                            and (d is None or not forbid[b][d]):
                        p[i + 1:j + 1] = p[i + 1:j + 1][::-1]
                        improved = True
        return p

    def or_opt(p):
        improved = True
        while improved:
            improved = False
            for i in range(len(p)):
                for seg in (1, 2, 3):
                    if i + seg > len(p):
                        break
                    block = p[i:i + seg]
                    rest = p[:i] + p[i + seg:]
                    for k in range(len(rest) + 1):
                        if k == i:
                            continue
                        cand = rest[:k] + block + rest[k:]
                        if path_cost(cand) < path_cost(p) - 1e-6:
                            p = cand; improved = True; break
                    if improved:
                        break
                if improved:
                    break
        return p

    best, best_c = None, float("inf")
    starts = list(range(n))
    if n > 12:
        starts = rng.sample(starts, 12)
    for s in starts:
        p = two_opt(nn(s))
        p = or_opt(p)
        c = path_cost(p)
        if c < best_c:
            best, best_c = p, c
    return best, best_c


def main():
    stations = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"]

    print("抠线路走廊 ...")
    masks = load_masks()

    report = []
    changes = 0
    for ln in lines:
        lid = ln["id"]
        key = COLOR_KEY.get(lid, lid)
        mask = masks.get(key)
        seq = [s for s in (ln.get("stations") or []) if s in stations]
        if mask is None or len(seq) < 2:
            report.append((lid, len(seq), None, None, 0))
            continue

        pts = [(float(stations[s]["x"]), float(stations[s]["y"])) for s in seq]
        n = len(pts)
        cov = [[0.0] * n for _ in range(n)]
        d = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                c = cover(mask, pts[i], pts[j])
                dd = math.dist(pts[i], pts[j])
                cov[i][j] = cov[j][i] = c
                d[i][j] = d[j][i] = dd

        forbid = [[False] * n for _ in range(n)]
        cost = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                c = cov[i][j]
                cost[i][j] = d[i][j] * (1.0 + LONG_EDGE * (1.0 - c)) + 1.0
                if c < OK_COVER:
                    forbid[i][j] = True

        # 如果禁得太多导致走不通，逐步放宽
        for relax in (0.0, 0.42, 0.28):
            f2 = [[forbid[i][j] if cov[i][j] < relax else False for j in range(n)]
                  for i in range(n)]
            order, _c = solve_path(n, cost, f2)
            used = [f2[order[i]][order[i + 1]] for i in range(n - 1)]
            if sum(used) == 0:
                break

        new_seq = [seq[i] for i in order]
        old_cov = [cov[i][i + 1] for i in range(n - 1)]
        new_cov = [cov[order[i]][order[i + 1]] for i in range(n - 1)]
        mo, mn = float(np.mean(old_cov)), float(np.mean(new_cov))

        # ★ 只在"确实更贴合原图"的时候才改这条线路的站序。
        #   盲目全局重排有时会因为个别站点坐标不准而把线路排得更乱，
        #   所以用覆盖率当裁判：不变好就不动。
        accept = (mn >= mo + 0.02) or (mn >= mo - 0.005 and min(new_cov) > min(old_cov) + 0.05)
        if not accept:
            new_seq = seq
            new_cov = old_cov
            used = [False] * (n - 1)

        if new_seq != seq:
            changes += 1
        report.append((lid, n, mo, float(np.mean(new_cov)),
                       sum(1 for x in used if x)))

        tag = "改" if new_seq != seq else "保持"
        print(f"\n{lid:>4}号线  站数 {n}  平均走廊覆盖率  "
              f"旧 {mo:.1%} → 新 {np.mean(new_cov):.1%}  [{tag}]")
        if new_seq != seq:
            print(f"      旧: {' → '.join(seq)}")
            print(f"      新: {' → '.join(new_seq)}")
        if new_cov and min(new_cov) < OK_COVER:
            worst = sorted(range(n - 1), key=lambda i: new_cov[i])[:4]
            print("      仍偏低的段: " + "  ".join(
                f"{new_seq[i]}→{new_seq[i+1]}({new_cov[i]:.0%})" for i in worst
                if new_cov[i] < OK_COVER))

        ln["stations"] = new_seq

    print("\n" + "=" * 80)
    olds = [r[2] for r in report if r[2] is not None]
    news = [r[3] for r in report if r[3] is not None]
    print(f"16 条线路平均走廊覆盖率：旧 {np.mean(olds):.1%} → 新 {np.mean(news):.1%}")
    print(f"站序有变动的线路：{changes} 条")

    if APPLY:
        ts = datetime.now().strftime("%m%d%H%M")
        shutil.copy2(SRC / "data" / "lines.json", SRC / "data" / f"lines.json.bak_order2_{ts}")
        (SRC / "data" / "lines.json").write_text(
            json.dumps(lj, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[OK] 已写回 lines.json（备份 .bak_order2_{ts}）")


if __name__ == "__main__":
    main()
