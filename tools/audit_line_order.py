"""
tools/audit_line_order.py
================================
站序审计：检查每条线路的站点顺序是否合理。

判定依据：
  · 逐个统计相邻站间距，找"远跳"（该段长度 > 中位数的 JUMP_K 倍）
  · 用"最近邻 + 2-opt"求一条更短的访问顺序作对照
  · 若优化后总长明显变短，说明原顺序有问题

用法：
    python tools/audit_line_order.py            # 只报告
    python tools/audit_line_order.py --fix      # 写回 lines.json（自动备份）
"""

import sys
import json
import shutil
import math
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_ROOT))

DATA = SRC_ROOT / "data"
JUMP_K = 3.0          # 超过中位数 3 倍算"远跳"


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def path_len(pts):
    return sum(dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))


def nn_order(pts, start):
    """从 start 出发的最近邻顺序。"""
    n = len(pts)
    remain = set(range(n))
    remain.discard(start)
    order = [start]
    cur = start
    while remain:
        nxt = min(remain, key=lambda j: dist(pts[cur], pts[j]))
        order.append(nxt)
        remain.discard(nxt)
        cur = nxt
    return order


def two_opt(pts, order):
    """2-opt 优化路径（保持开放路径）。"""
    n = len(order)
    improved = True
    best = path_len([pts[i] for i in order])
    while improved:
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                l = path_len([pts[k] for k in cand])
                if l < best - 1e-6:
                    best = l
                    order = cand
                    improved = True
        n = len(order)
    return order, best


def best_order(pts):
    """多起点最近邻 + 2-opt，取最优。"""
    n = len(pts)
    best = None
    best_len = float("inf")
    # 起点候选：所有点太多，取若干个（端点通常就是起点）
    starts = list(range(min(n, 12))) + [n - 1]
    for s in starts:
        o = nn_order(pts, s)
        o, l = two_opt(pts, o)
        if l < best_len:
            best_len = l
            best = o
    return best, best_len


def main():
    do_fix = "--fix" in sys.argv

    stations = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
    lines_doc = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))
    lines = lines_doc["lines"]

    print(f"线路数: {len(lines)}\n")
    print(f"{'线路':<22} {'站数':>4} {'原总长':>9} {'优化后':>9} {'缩减':>7} {'远跳段':>6} {'结论':<10}")
    print("-" * 82)

    to_fix = []
    for ln in lines:
        seq = ln.get("stations") or []
        pts, names = [], []
        for nm in seq:
            st = stations.get(nm)
            if st:
                pts.append((float(st["x"]), float(st["y"])))
                names.append(nm)
        if len(pts) < 3:
            continue

        cur_len = path_len(pts)
        segs = [dist(pts[i - 1], pts[i]) for i in range(1, len(pts))]
        med = sorted(segs)[len(segs) // 2] if segs else 1.0
        jumps = [i for i, s in enumerate(segs, start=1) if s > med * JUMP_K]

        opt, opt_len = best_order(pts)
        cut = (cur_len - opt_len) / cur_len * 100 if cur_len else 0

        verdict = "OK"
        if cut > 12 or len(jumps) > 0:
            verdict = "需修"
        label = f"{ln.get('name','')} {ln.get('alias','')}".strip()
        print(f"{label:<22} {len(pts):>4} {cur_len:>9.0f} {opt_len:>9.0f} {cut:>6.1f}% {len(jumps):>6} {verdict:<10}")

        if verdict == "需修":
            to_fix.append((ln, names, [names[i] for i in opt], opt_len, cur_len))

    print()
    if not to_fix:
        print("所有线路站序正常。")
        return

    print(f"需要修正的线路: {len(to_fix)} 条")
    for ln, old, new, ol, cl in to_fix[:6]:
        print(f"\n  {ln.get('name')} ({ln.get('alias')})  {cl:.0f} → {ol:.0f}")
        print(f"    原顺序: {' → '.join(old)}")
        print(f"    新顺序: {' → '.join(new)}")

    if not do_fix:
        print("\n（加 --fix 参数可写回 lines.json）")
        return

    bak = DATA / "lines.json.bak_order"
    shutil.copy2(DATA / "lines.json", bak)
    print(f"\n[BACKUP] 已备份 → {bak}")

    fix_map = {ln["id"]: new for ln, old, new, ol, cl in to_fix}
    for ln in lines:
        if ln["id"] in fix_map:
            ln["stations"] = fix_map[ln["id"]]
    (DATA / "lines.json").write_text(
        json.dumps(lines_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] 已写回 {DATA / 'lines.json'}")


if __name__ == "__main__":
    main()
