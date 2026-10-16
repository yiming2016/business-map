"""
tools/trace_line_order.py
================================
★ 直接按"原图上该线路颜色的像素"来确定站序 —— 真正的对照图片。

原理：
  一条线路在图上就是一条连续的彩色带。若站序正确，那么"相邻两站之间的
  连线"应该整段都压在图上这条彩色带上。于是：
    给每对站点算一个「覆盖率」= 连线上落在该线路颜色上的采样点比例，
    覆盖率高的边才是真正的相邻关系。
  然后在这张"高覆盖边"构成的图里找一条把全部站点串起来的路径 = 正确站序。

用法：
    python tools/trace_line_order.py            # 只报告
    python tools/trace_line_order.py --fix      # 写回 lines.json（自动备份）
"""

import sys
import json
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

SRC_ROOT = Path(__file__).resolve().parent.parent
DATA = SRC_ROOT / "data"
ORIGINAL = SRC_ROOT / "assets" / "shenzhen_metro.png"

WORK = 2000              # 工作分辨率（原图 8000 → 2000，缩小 4 倍）
COLOR_TOL = 62           # 颜色距离容差
DILATE = 1               # 掩膜膨胀次数（容忍 1px 偏差）
GOOD = 0.72              # 覆盖率高于此值算"确实是相邻"
SAMPLES = 160


def hex_to_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)], dtype=np.float32)


def build_masks(img, lines):
    small = img.resize((WORK, WORK), Image.LANCZOS)
    a = np.asarray(small).astype(np.float32)
    masks = {}
    for ln in lines:
        col = hex_to_rgb(ln.get("color", "#888888"))
        d = np.sqrt(((a - col) ** 2).sum(axis=2))
        m = d < COLOR_TOL
        if DILATE:
            m = ndimage.binary_dilation(m, iterations=DILATE)
        masks[ln["id"]] = m
    return masks, a.shape[0]


def coverage(mask, p, q, k, n=SAMPLES):
    """线段 p→q 上落在掩膜里的采样点比例。p/q 为原图坐标。"""
    p = np.array(p, dtype=np.float64) * k
    q = np.array(q, dtype=np.float64) * k
    ts = np.linspace(0.12, 0.88, n)
    xs = np.clip((p[0] + (q[0] - p[0]) * ts).astype(int), 0, mask.shape[1] - 1)
    ys = np.clip((p[1] + (q[1] - p[1]) * ts).astype(int), 0, mask.shape[0] - 1)
    return float(mask[ys, xs].mean())


def path_order(pts, cov, extra_last=None):
    """
    在覆盖率图上找一条把全部点串起来的路径。
    先用覆盖率做最近邻 + 2-opt，覆盖率作为主目标、距离作次目标。
    """
    n = len(pts)
    dist = [[math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) for j in range(n)] for i in range(n)]
    C = [[cov(i, j) for j in range(n)] for i in range(n)]

    def score(order):
        s = 0.0
        for i in range(1, len(order)):
            a, b = order[i - 1], order[i]
            s += (1.0 - C[a][b]) * dist[a][b] + 0.02 * C[a][b] * dist[a][b]
        return s

    best_o, best_s = None, float("inf")
    for st in range(n):
        # 最近邻：优先覆盖率高的
        remain = set(range(n)) - {st}
        o = [st]
        cur = st
        while remain:
            nx = min(remain, key=lambda j: (1.0 - C[cur][j]) * dist[cur][j])
            o.append(nx)
            remain.discard(nx)
            cur = nx

        # 2-opt（只用局部变量，别把全局最优串进来）
        local = score(o)
        improved = True
        while improved:
            improved = False
            for i in range(1, len(o) - 1):
                for j in range(i + 1, len(o)):
                    cand = o[:i] + o[i:j + 1][::-1] + o[j + 1:]
                    c = score(cand)
                    if c < local - 1e-9:
                        o, local = cand, c
                        improved = True
        if local < best_s:
            best_s, best_o = local, o
    if best_o is None:
        best_o = list(range(n))
    return best_o


def order_stats(names, pts, cov):
    tot = len(names) - 1
    good = sum(1 for i in range(1, len(names))
               if cov(i - 1, i) >= GOOD)
    covs = [cov(i - 1, i) for i in range(1, len(names))]
    return good, tot, (sum(covs) / len(covs) if covs else 0.0)


def main():
    do_fix = "--fix" in sys.argv

    img = Image.open(ORIGINAL).convert("RGB")
    lines_doc = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))
    lines = lines_doc["lines"]
    stations = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]

    masks, H = build_masks(img, lines)
    k = WORK / 8000.0

    print(f"{'线路':<18} {'站数':>4} {'掩膜像素':>9} {'原来好边':>9} {'现在好边':>9} {'平均覆盖':>9}")
    print("-" * 70)

    plan = []
    for ln in lines:
        seq = [n for n in (ln.get("stations") or []) if n in stations]
        if len(seq) < 3:
            continue
        pts = [(float(stations[n]["x"]), float(stations[n]["y"])) for n in seq]
        mask = masks[ln["id"]]
        ncells = int(mask.sum())

        def cv(i, j, _m=mask, _p=pts):
            return coverage(_m, _p[i], _p[j], k)

        cur_good, cur_tot, cur_avg = order_stats(seq, pts, cv)
        order = path_order(pts, cv)
        new_seq = [seq[i] for i in order]
        npts = [pts[i] for i in order]

        def cv2(i, j, _m=mask, _p=npts):
            return coverage(_m, _p[i], _p[j], k)

        new_good, new_tot, new_avg = order_stats(new_seq, npts, cv2)

        print(f"{ln.get('name',''):<18} {len(seq):>4} {ncells:>9} "
              f"{cur_good:>4}/{cur_tot:<4} {new_good:>4}/{new_tot:<4} {new_avg:>8.2f}")
        plan.append((ln, seq, new_seq, cur_good, new_good, cur_avg, new_avg))

    if not do_fix:
        print("\n（加 --fix 参数可写回 lines.json）")
        return

    bak = DATA / "lines.json.bak_trace"
    if not bak.exists():
        shutil.copy2(DATA / "lines.json", bak)
        print(f"[BACKUP] {bak}")

    changed = 0
    for ln, old, new, cg, ng, ca, na in plan:
        # 只在新顺序"好边"更多时才改，避免把本来对的顺序改坏
        if ng > cg:
            ln["stations"] = new
            changed += 1
    (DATA / "lines.json").write_text(
        json.dumps(lines_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] 已写回，改动 {changed} 条线路")


if __name__ == "__main__":
    main()
