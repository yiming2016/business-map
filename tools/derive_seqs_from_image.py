"""从原图直接反推每条线的完整站序（最终权威数据源）。

原理：
  1. 按实测线色抠走廊掩膜（容差 12，不加膨胀以免串线）
  2. 走廊外扩 3px 作为"可行走带"；带内非掩膜像素通行代价 8（模拟被别的线盖住的交叉口）
  3. Dijkstra（8 邻接，对角×1.414）求测地距离
  4. 取该线走廊上的所有标记；双 BFS 找两个端点；从一端出发按测地距离排序
  5. 每个标记用最近的纯中文 OCR 标签命名

输出：data/_seq_from_image.txt（逐线打印 站序 + 标记坐标 + 命名距离），
      以及 data/_seq_from_image.json 供程序读取。

用法:
  python tools/derive_seqs_from_image.py                # 全部彩色线路
  python tools/derive_seqs_from_image.py 12 7 16        # 指定
"""
import heapq
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
IMG = SRC / "assets" / "shenzhen_metro.png"

DS = 2
TOL = 12
BAND = 9          # 走廊外扩（DS 像素）
SERVE_R = 22.0    # 标记判定"属于该线"的距离（原图 px）
NAME_R = 340.0    # 标记 -> OCR 名 最大距离
CROSS_COST = 8.0  # 穿越非掩膜像素的代价

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_offcorridor import LINE_RGB  # noqa: E402

CN = re.compile(r"^[\u4e00-\u9fff]{2,7}$")


def dijkstra(band, mask, seed):
    h, w = band.shape
    INF = float("inf")
    dist = np.full((h, w), INF)
    sy, sx = seed
    if not band[sy, sx]:
        ys, xs = np.nonzero(band)
        i = int(np.argmin((ys - sy) ** 2 + (xs - sx) ** 2))
        sy, sx = int(ys[i]), int(xs[i])
    dist[sy, sx] = 0.0
    pq = [(0.0, sy, sx)]
    cost = np.where(mask, 1.0, CROSS_COST)
    SQ2 = 1.41421356
    while pq:
        d, y, x = heapq.heappop(pq)
        if d > dist[y, x]:
            continue
        for dy, dx, k in ((-1, 0, 1), (1, 0, 1), (0, -1, 1), (0, 1, 1),
                          (-1, -1, SQ2), (-1, 1, SQ2), (1, -1, SQ2), (1, 1, SQ2)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and band[ny, nx]:
                nd = d + k * cost[ny, nx]
                if nd < dist[ny, nx]:
                    dist[ny, nx] = nd
                    heapq.heappush(pq, (nd, ny, nx))
    return dist


def nn_chain(pts, cap_mult=2.6):
    """最近邻链重建：枚举起点，取总长最小的那条链。
    pts: [(name, x, y, w, h, namedist), ...]
    返回 (ordered_list, flagged_pairs)
    """
    n = len(pts)
    if n <= 2:
        return list(pts), []
    best = None
    for s in range(n):
        left = set(range(n))
        cur = s
        left.discard(s)
        chain = [cur]
        while left:
            cand = sorted(left, key=lambda j: (pts[j][1] - pts[cur][1]) ** 2 + (pts[j][2] - pts[cur][2]) ** 2)
            nxt = cand[0]
            chain.append(nxt)
            left.discard(nxt)
            cur = nxt
        L = sum(math.dist((pts[chain[i]][1], pts[chain[i]][2]),
                          (pts[chain[i + 1]][1], pts[chain[i + 1]][2])) for i in range(n - 1))
        if best is None or L < best[0]:
            best = (L, chain)
    chain = best[1]
    ds = [math.dist((pts[chain[i]][1], pts[chain[i]][2]),
                    (pts[chain[i + 1]][1], pts[chain[i + 1]][2])) for i in range(n - 1)]
    med = sorted(ds)[len(ds) // 2] if ds else 1
    flag = [(pts[chain[i]][0], pts[chain[i + 1]][0], round(ds[i]))
            for i in range(len(ds)) if ds[i] > cap_mult * max(med, 60)]
    return [pts[i] for i in chain], flag


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("-")]
    im = Image.open(IMG).convert("RGB")
    img = np.asarray(im.resize((im.width // DS, im.height // DS), Image.NEAREST))
    mk = json.loads((DATA / "markers.json").read_text(encoding="utf-8"))["markers"]
    lb = json.loads((DATA / "ocr_labels.json").read_text(encoding="utf-8"))
    st = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
    ln = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))["lines"]

    names = [(b["text"].replace(" ", ""), b["x"] + b["w"] / 2, b["y"] + b["h"] / 2,
              b.get("score", 0)) for b in lb if CN.match(b["text"].replace(" ", ""))]

    SKIP = {"有轨电车", "有轨电车支线", "坪山云巴"}
    out = {}
    lines_txt = []
    for entry in ln:
        lid = entry["id"]
        if lid in SKIP or (want and lid not in want):
            continue
        rgb = LINE_RGB[lid]
        c = np.array(rgb, np.int16)
        d = np.zeros(img.shape[:2], np.int16)
        for k in range(3):
            d = np.maximum(d, np.abs(img[:, :, k].astype(np.int16) - c[k]))
        mask = d <= TOL
        if mask.sum() < 500:
            continue
        dt = ndimage.distance_transform_edt(~mask) * DS

        served = [i for i, m in enumerate(mk)
                  if dt[int(round(m["y"] / DS)), int(round(m["x"] / DS))] <= SERVE_R]
        if len(served) < 3:
            lines_txt.append(f"[{lid}] 走廊上标记不足（{len(served)}）")
            continue

        pts = []
        for i in served:
            m = mk[i]
            nm, nd = "?", -1.0
            for t, tx, ty, sc in names:
                r = math.dist((tx, ty), (m["x"], m["y"]))
                if r <= NAME_R and (nd < 0 or r < nd):
                    nm, nd = t, r
            pts.append((nm, m["x"], m["y"], m.get("w"), m.get("h"), nd))
        chain, flag = nn_chain(pts)
        # 同名去重
        seen, uniq = set(), []
        for p in chain:
            if p[0] != "?" and p[0] in seen:
                continue
            seen.add(p[0])
            uniq.append(p)
        out[lid] = uniq
        lines_txt.append(f"\n===== {lid}   标记 {len(uniq)} 个（原始 {len(served)}）"
                         + ("   !! 可疑跳段: " + "、".join(f"{a}->{b}({d}px)" for a, b, d in flag)
                            if flag else ""))
        for nm, x, y, w, h, nd in uniq:
            lines_txt.append(f"   {nm:<10s} ({x:>7.1f},{y:>7.1f}) {w}x{h}  名距={nd:>5.0f}")

    (DATA / "_seq_from_image.txt").write_text("\n".join(lines_txt), encoding="utf-8")
    (DATA / "_seq_from_image.json").write_text(
        json.dumps({k: [[r[0], r[1], r[2]] for r in v] for k, v in out.items()},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines_txt))
    print("\n[OK] data/_seq_from_image.txt / .json")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
