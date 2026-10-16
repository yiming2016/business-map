"""沿走廊反推站序：给定线路颜色，抠出走廊掩膜 -> 求主连通域 -> 端点间测地线
-> 把该线所有站投影到中心线上按弧长排序。用来校验/纠正 lines.json 的站序，
并揪出坐标严重偏离走廊的站。

为了速度，内部把原图按 DS 倍降采样（最近邻，保色）。

用法:
  python tools/order_by_corridor.py            # 全部线路体检
  python tools/order_by_corridor.py 12 13      # 只看指定线路
"""
import json
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
IMG = SRC / "assets" / "shenzhen_metro.png"

DS = 2               # 降采样倍数
COLOR_TOL = 30
DILATE = 6
MAX_OFF = 90.0       # 站点到走廊的最大允许距离（原图像素）

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rebuild_lines_v24 import LINES_META  # noqa: E402


def hex2rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.int16)


def corridor_mask(img, hexcolor, tol=COLOR_TOL, dilate=DILATE):
    c = hex2rgb(hexcolor)
    d = np.zeros(img.shape[:2], np.int16)
    for k in range(3):
        d = np.maximum(d, np.abs(img[:, :, k].astype(np.int16) - c[k]))
    m = d <= tol
    if dilate:
        m = ndimage.binary_dilation(m, np.ones((3, 3), bool), iterations=dilate)
    return m


def largest_component(mask):
    lab, n = ndimage.label(mask, np.ones((3, 3), int))
    if n == 0:
        return None, 0, 0
    sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
    keep = int(np.argmax(sizes)) + 1
    return lab == keep, n, int(sizes[keep - 1])


def bfs_far(mask, start):
    h, w = mask.shape
    dist = np.full((h, w), -1, np.int32)
    sy, sx = int(start[0]), int(start[1])
    if not mask[sy, sx]:
        ys, xs = np.nonzero(mask)
        i = int(np.argmin((ys - sy) ** 2 + (xs - sx) ** 2))
        sy, sx = int(ys[i]), int(xs[i])
    dist[sy, sx] = 0
    q = deque([(sy, sx)])
    far = (sy, sx)
    fd = 0
    while q:
        y, x = q.popleft()
        d = dist[y, x]
        if d > fd:
            fd, far = d, (y, x)
        if y + 1 < h and mask[y + 1, x] and dist[y + 1, x] < 0:
            dist[y + 1, x] = d + 1; q.append((y + 1, x))
        if y > 0 and mask[y - 1, x] and dist[y - 1, x] < 0:
            dist[y - 1, x] = d + 1; q.append((y - 1, x))
        if x + 1 < w and mask[y, x + 1] and dist[y, x + 1] < 0:
            dist[y, x + 1] = d + 1; q.append((y, x + 1))
        if x > 0 and mask[y, x - 1] and dist[y, x - 1] < 0:
            dist[y, x - 1] = d + 1; q.append((y, x - 1))
    return far, fd


def path_between(mask, a, b):
    h, w = mask.shape
    prev = np.full((h, w, 2), -1, np.int32)
    seen = np.zeros((h, w), bool)
    seen[a] = True
    q = deque([a])
    hit = (a == b)
    while q and not hit:
        y, x = q.popleft()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    prev[ny, nx] = (y, x)
                    if (ny, nx) == b:
                        hit = True
                    q.append((ny, nx))
    if not hit:
        return None
    out = [b]
    cur = b
    while cur != a:
        cur = tuple(prev[cur[0], cur[1]])
        out.append(cur)
    out.reverse()
    return out


def simplify(pts, step):
    if not pts:
        return pts
    out = pts[::step]
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def main():
    im = Image.open(IMG).convert("RGB")
    W, H = im.size
    small = im.resize((W // DS, H // DS), Image.NEAREST)
    img = np.asarray(small)
    st = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
    ln = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))["lines"]

    want = [a for a in sys.argv[1:] if not a.startswith("-")]
    report = {}
    for entry in ln:
        lid = entry["id"]
        if want and lid not in want:
            continue
        color = (LINES_META.get(lid) or (None, entry.get("color")))[1] or entry.get("color")
        seq = [n for n in entry["stations"] if n in st]
        if len(seq) < 2:
            continue
        mask = corridor_mask(img, color)
        comp, ncomp, csize = largest_component(mask)
        if comp is None:
            print(f"[{lid:>5s}] 找不到走廊（色 {color}）")
            continue
        pts_all = [(n, st[n]["x"] / DS, st[n]["y"] / DS) for n in seq]
        seed = pts_all[0]
        far1, _ = bfs_far(comp, (seed[2], seed[1]))
        far2, geo = bfs_far(comp, far1)
        path = path_between(comp, far1, far2)
        if not path:
            print(f"[{lid:>5s}] 走廊不通 主域={csize} 主域像素总数={csize} 连通域数={ncomp}")
            continue
        step = max(4, len(path) // 600)
        P = np.array([[p[0], p[1]] for p in simplify(path, step)], float)
        # 累积弧长
        seg = np.hypot(*(P[1:] - P[:-1]).T)
        cum = np.concatenate([[0], np.cumsum(seg)])
        # 每个站投影
        proj = []
        for n, x, y in pts_all:
            a = P[:-1]
            v = P[1:] - a
            L2 = (v ** 2).sum(1); L2[L2 == 0] = 1
            t = np.clip(((np.array([y, x]) - a) * v).sum(1) / L2, 0, 1)
            foot = a + t[:, None] * v
            d = np.hypot(foot[:, 0] - y, foot[:, 1] - x)
            i = int(np.argmin(d))
            arc = cum[i] + t[i] * seg[i]
            proj.append((float(arc), n, float(d[i]) * DS))
        proj.sort()
        ordered = [p[1] for p in proj]
        off = [(p[1], round(p[2])) for p in proj if p[2] > MAX_OFF]
        report[lid] = {"order": ordered, "len": round(float(cum[-1]) * DS)}
        same = ordered == seq
        print(f"[{lid:>5s}] 主域 {csize:>7d}px  走廊长 {cum[-1]*DS:>6.0f}px  站数 {len(seq):>2d}"
              f"{'   OK 站序一致' if same else '   ★站序不一致'}")
        if not same:
            print("        沿走廊: " + " → ".join(ordered))
            print("        现  表: " + " → ".join(seq))
        if off:
            print("        偏离走廊: " + "、".join(f"{n}({d}px)" for n, d in
                                                 sorted(off, key=lambda z: -z[1])))

    (DATA / "_corridor_order.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n[OK] 已导出 data/_corridor_order.json")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
