# -*- coding: utf-8 -*-
"""只读探针：官方原图里每个站附近到底有没有"本站所属线路的颜色"像素？

用途：给 tools/build_trace_cloud.py 定颜色容差 TOL —— 容差太小会把抗锯齿边缘
全丢掉（走廊断成虚线），太大会把别的线/文字吸进来。

判据：对每个站，在官方图 (x, y) 周围 R 像素的窗口里找"最像该线颜色"的像素，
      报出最小色差和距离。理想情况：每个站都能在 30px 内找到色差 < TOL 的像素。
"""
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

import numpy as np                       # noqa: E402
from PIL import Image                    # noqa: E402

Image.MAX_IMAGE_PIXELS = None
R = 40


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def main():
    st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj
    img = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)
    H, W = img.shape[:2]
    print("原图 %dx%d" % (W, H))

    for L in lines:
        lid = str(L.get("id"))
        c = hex2rgb(L.get("color", "#000000"))
        seq = L.get("stations") or []
        worst_d = 0.0
        worst_dist = 0.0
        miss = []
        n = 0
        for name in seq:
            s = st.get(name)
            if not s:
                continue
            x, y = int(round(float(s.get("x", 0)))), int(round(float(s.get("y", 0))))
            if not (0 <= x < W and 0 <= y < H):
                continue
            n += 1
            x0, x1 = max(0, x - R), min(W, x + R)
            y0, y1 = max(0, y - R), min(H, y + R)
            sub = img[y0:y1, x0:x1]
            d = np.abs(sub - np.array(c, dtype=np.int16)).max(axis=2)
            md = float(d.min())
            if md > worst_d:
                worst_d = md
            if md > 60:
                yy, xx = np.unravel_index(int(np.argmin(d)), d.shape)
                dist = ((xx + x0 - x) ** 2 + (yy + y0 - y) ** 2) ** 0.5
                miss.append((name, int(md), int(dist)))
                worst_dist = max(worst_dist, dist)
            else:
                yy, xx = np.unravel_index(int(np.argmin(d)), d.shape)
                dist = ((xx + x0 - x) ** 2 + (yy + y0 - y) ** 2) ** 0.5
                worst_dist = max(worst_dist, dist)
        print("%-8s %s  站 %2d  最差色差 %3.0f  最差距离 %5.1f  超60的 %s"
              % (lid, L.get("color"), n, worst_d, worst_dist,
                 miss[:4] if miss else "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
