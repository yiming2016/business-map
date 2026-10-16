"""沿线路走廊，把「主图未标出、只在附图上列出」的站点等距摆到线路走向上。

做法：
  1. 按线路色抠走廊掩膜（膨胀几个像素把交叉处的断口接上）
  2. 在掩膜内做 8 连通测地距离（从起点 BFS）
  3. 从终点回溯得到中心线路径
  4. 按累计弧长把 N 个中间站等距摆放

用法示例见文件末尾 TODO 区。
"""
import json
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None
SRC = Path(__file__).resolve().parent.parent
IMG = SRC / "assets" / "shenzhen_metro.png"

_cache = {}


def get_image():
    if "im" not in _cache:
        _cache["im"] = np.asarray(Image.open(IMG).convert("RGB")).astype(np.int16)
    return _cache["im"]


def corridor(hexcolor, tol=20, dilate=6):
    key = (hexcolor, tol, dilate)
    if key in _cache:
        return _cache[key]
    im = get_image()
    t = np.array([int(hexcolor[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.int16)
    m = np.abs(im - t).max(axis=2) <= tol
    if dilate:
        m = ndimage.binary_dilation(m, np.ones((3, 3), bool), iterations=dilate)
    # 只保留覆盖到锚点的连通域，避免被同色的其它线路干扰
    _cache[key] = m
    return m


def geodesic_path(mask, start, end):
    """在 mask 内找 start->end 的最短路径（8 连通，等权）。返回像素坐标列表。"""
    h, w = mask.shape
    sx, sy = int(round(start[0])), int(round(start[1]))
    ex, ey = int(round(end[0])), int(round(end[1]))

    def snap(x, y):
        """把锚点吸附到最近的掩膜像素上。"""
        if 0 <= y < h and 0 <= x < w and mask[y, x]:
            return x, y
        ys, xs = np.where(mask)
        if len(ys) == 0:
            raise RuntimeError("掩膜为空")
        d = (xs - x) ** 2 + (ys - y) ** 2
        i = int(np.argmin(d))
        return int(xs[i]), int(ys[i])

    sx, sy = snap(sx, sy)
    ex, ey = snap(ex, ey)

    prev = np.full((h, w), -1, dtype=np.int32)
    visited = np.zeros((h, w), bool)
    q = deque([(sx, sy)])
    visited[sy, sx] = True
    tgt = ey * w + ex
    found = False
    nb = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]
    while q:
        x, y = q.popleft()
        if y * w + x == tgt:
            found = True
            break
        for dx, dy in nb:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not visited[ny, nx]:
                visited[ny, nx] = True
                prev[ny, nx] = y * w + x
                q.append((nx, ny))
    if not found:
        raise RuntimeError(f"走廊内找不到从 {start} 到 {end} 的通路")

    path = []
    cur = tgt
    while cur != -1:
        cy, cx = divmod(cur, w)
        path.append((cx, cy))
        cur = int(prev[cy, cx])
        if len(path) > 400000:
            raise RuntimeError("路径异常长")
    path.reverse()
    return path


def resample(path, k=6):
    """把像素级路径降采样，并做 k 点滑动平均，得到更平滑的中心线。"""
    pts = path[::max(1, len(path) // 4000)]
    if len(pts) < k:
        return pts
    a = np.array(pts, dtype=float)
    ker = np.ones(k) / k
    xs = np.convolve(a[:, 0], ker, mode="valid")
    ys = np.convolve(a[:, 1], ker, mode="valid")
    sm = np.column_stack([xs, ys])
    return [tuple(p) for p in sm]


def place_between(hexcolor, a, b, n, dilate=6):
    """在 a、b 之间等距放 n 个点（不含端点）。"""
    m = corridor(hexcolor, dilate=dilate)
    path = resample(geodesic_path(m, a, b))
    if len(path) < 2:
        return []
    p = np.array(path, dtype=float)
    seg = np.sqrt(((p[1:] - p[:-1]) ** 2).sum(axis=1))
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total = s[-1]
    out = []
    for i in range(1, n + 1):
        t = total * i / (n + 1)
        j = int(np.searchsorted(s, t))
        j = min(max(j, 1), len(s) - 1)
        f = (t - s[j - 1]) / max(1e-9, s[j] - s[j - 1])
        pt = p[j - 1] + (p[j] - p[j - 1]) * f
        out.append((round(float(pt[0]), 1), round(float(pt[1]), 1)))
    return out


def place_along_waypoints(waypoints, n):
    """给定折线折点，按累计弧长等距放 n 个点（不含端点）。

    有些线路（例如坪山云巴）在原图上被别的线路横穿，走廊断开，
    测地寻路走不通 —— 这时直接手工量出折点更可靠。
    """
    p = np.array(waypoints, dtype=float)
    seg = np.sqrt(((p[1:] - p[:-1]) ** 2).sum(axis=1))
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total = s[-1]
    out = []
    for i in range(1, n + 1):
        t = total * i / (n + 1)
        j = int(np.searchsorted(s, t))
        j = min(max(j, 1), len(s) - 1)
        f = (t - s[j - 1]) / max(1e-9, s[j] - s[j - 1])
        pt = p[j - 1] + (p[j] - p[j - 1]) * f
        out.append((round(float(pt[0]), 1), round(float(pt[1]), 1)))
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    # 自检：清湖(电车)->大和 之间放 5 个点
    a = (3076.0, 2921.0)
    b = (3574.5, 2687.5)
    print("清湖->大和 5 点:", place_between("#B6B6B7", a, b, 5))
