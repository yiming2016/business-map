"""
tools/optimize_line_order.py
================================
按"沿线路实际走向"重排每条线路的站点顺序。

原理：
  站点的坐标本身是从原图读出来的，位置大致正确；出问题的是**顺序** ——
  顺序一错，画出来的线就会来回折返、斜穿整张图（就是"乱"的来源）。
  所以用「多起点最近邻 + 2-opt」求一条总长最短的访问顺序，
  等价于"沿着站点走一遍不回头"，即原图上的线路走向。

另外加了一点"示意图偏好"：原图是横平竖直 + 45° 斜线的拓扑图，
  所以对轴对齐/45°的连线给一点奖励，能进一步贴近原图风格。

用法：
    python tools/optimize_line_order.py           # 只报告
    python tools/optimize_line_order.py --fix     # 写回 lines.json（自动备份）
"""

import sys
import json
import math
import shutil
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
DATA = SRC_ROOT / "data"

ANGLE_WEIGHT = 0.0    # 45° 对齐偏好强度。实测反而更差（坐标是肉眼读的，有噪声），
                      # 所以默认关闭，用纯"最短访问路径"。


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def edge_cost(a, b):
    """连线代价：距离 × 角度惩罚（越接近 0/45/90/135° 越便宜）。"""
    d = dist(a, b)
    if d < 1e-6:
        return 1e-6
    ang = math.atan2(b[1] - a[1], b[0] - a[0]) % (math.pi / 4)
    dev = min(ang, math.pi / 4 - ang) / (math.pi / 8)     # 0..1
    return d * (1.0 + ANGLE_WEIGHT * dev)


def order_cost(pts, order):
    return sum(edge_cost(pts[order[i - 1]], pts[order[i]]) for i in range(1, len(order)))


def nn_order(pts, start):
    n = len(pts)
    remain = set(range(n))
    remain.discard(start)
    order = [start]
    cur = start
    while remain:
        nxt = min(remain, key=lambda j: edge_cost(pts[cur], pts[j]))
        order.append(nxt)
        remain.discard(nxt)
        cur = nxt
    return order


def two_opt(pts, order):
    n = len(order)
    best = order_cost(pts, order)
    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                c = order_cost(pts, cand)
                if c < best - 1e-9:
                    best = c
                    order = cand
                    improved = True
    return order, best


def best_order(pts):
    n = len(pts)
    best, best_c = None, float("inf")
    # 起点候选：所有站点都试一遍（n ≤ 34，很快）
    for s in range(n):
        o = nn_order(pts, s)
        o, c = two_opt(pts, o)
        if c < best_c:
            best_c, best = c, o
    return best, best_c


def raw_len(pts, order):
    return sum(dist(pts[order[i - 1]], pts[order[i]]) for i in range(1, len(order)))


def main():
    do_fix = "--fix" in sys.argv

    stations = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
    lines_doc = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))
    lines = lines_doc["lines"]

    print(f"{'线路':<20} {'站数':>4} {'原里程':>9} {'新里程':>9} {'缩减':>7}")
    print("-" * 58)

    plan = []
    for ln in lines:
        seq = [n for n in (ln.get("stations") or []) if n in stations]
        if len(seq) < 3:
            continue
        pts = [(float(stations[n]["x"]), float(stations[n]["y"])) for n in seq]
        old_len = raw_len(pts, list(range(len(pts))))
        order, _ = best_order(pts)
        new_len = raw_len(pts, order)
        new_seq = [seq[i] for i in order]
        cut = (old_len - new_len) / old_len * 100 if old_len else 0
        print(f"{ln.get('name',''):<20} {len(pts):>4} {old_len:>9.0f} {new_len:>9.0f} {cut:>6.1f}%")
        plan.append((ln, seq, new_seq, old_len, new_len))

    tot_old = sum(p[3] for p in plan)
    tot_new = sum(p[4] for p in plan)
    print("-" * 58)
    print(f"{'合计':<20} {'':>4} {tot_old:>9.0f} {tot_new:>9.0f} "
          f"{(tot_old - tot_new) / tot_old * 100:>6.1f}%")

    if not do_fix:
        print("\n（加 --fix 参数可写回 lines.json）")
        return

    bak = DATA / "lines.json.bak_order"
    if not bak.exists():
        shutil.copy2(DATA / "lines.json", bak)
        print(f"\n[BACKUP] {bak}")

    changed = 0
    for ln, old, new, _, _ in plan:
        if old != new:
            ln["stations"] = new
            changed += 1
    (DATA / "lines.json").write_text(
        json.dumps(lines_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] 已写回 {DATA / 'lines.json'}，改动 {changed} 条线路")


if __name__ == "__main__":
    main()
