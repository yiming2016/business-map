# -*- coding: utf-8 -*-
"""只读：量原图里"线路末端号码方块"的真实位置/大小，用来校验我们的摆位规则。

★ 为什么用**距离变换**而不是连通域：方块跟线路是连着的，连通域的 bbox 会铺满
  整条线（第一版就栽在这，全都"没找到"）。而实心方块内部到白底的距离很大
  （128 的方块 ⇒ 中心 DT≈60+，12px 的线 ⇒ DT≤6，胶囊 26 宽 ⇒ DT≤13），
  用 DT 阈值一下就把"大块实心"挑出来了。

用法: python tools/_measure_badges.py
产物: logs/_badges_measure.txt
环境变量: BADGE_RAD（搜索半径，默认 260）、BADGE_DT（实心阈值，默认 18）
"""
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from core.data_manager import get_data_manager          # noqa: E402
from ui.map_view import line_station_xy                 # noqa: E402

RAD = int(os.environ.get("BADGE_RAD", 260))
DT_THR = float(os.environ.get("BADGE_DT", 18.0))


def hex2rgb(h):
    h = str(h).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


BODY_DT = 7.0       # "厚像素"阈值：12px 的线 DT≤6 会被排除，方块内部全留下
EDGE_PAD = 14.0     # bbox 到方块真实边缘的距离 ≈ 2×BODY_DT


def blobs(mask):
    """找出掩膜里所有"大块实心区"，返回 [(cy, cx, w, h, dt_max), ...]（按 dt 降序）。

    ★ 两道坎，缺一不可：
      ① 种子点要 DT≥18 —— 只有大方块内部才有这么大的 DT（胶囊 26 宽 DT=13）；
      ② 从种子点只在 DT≥7 的像素里连通 —— 这样把"连在方块上的那条 12px 的线"
         切掉（线的 DT≤6），拿到的是**方块本身**的 bbox，白字是内部空洞不影响。
    """
    dt = ndimage.distance_transform_edt(mask)
    mx = ndimage.maximum_filter(dt, size=41)
    peaks = (dt >= DT_THR) & (dt == mx)
    if not peaks.any():
        return []
    body, nb = ndimage.label(dt >= BODY_DT)
    seen = {}
    for cy, cx in zip(*np.where(peaks)):
        lb = body[cy, cx]
        if lb == 0:
            continue
        d = float(dt[cy, cx])
        if lb not in seen or d > seen[lb][0]:
            seen[lb] = (d, cy, cx)
    out = []
    for lb, (d, cy, cx) in seen.items():
        ys, xs = np.where(body == lb)
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        w = (x1 - x0 + 1) + EDGE_PAD
        h = (y1 - y0 + 1) + EDGE_PAD
        if max(w, h) < 55 or max(w, h) > 260:
            continue
        if min(w, h) / float(max(w, h)) < 0.75:     # 不够方 ⇒ 是胶囊不是号码方块
            continue
        out.append(((y0 + y1) / 2.0, (x0 + x1) / 2.0, w, h, d))
    out.sort(key=lambda t: -t[4])
    return out


def main():
    dm = get_data_manager()
    stations = dm.all_stations()
    lines = dm.all_lines()

    img = np.asarray(Image.open(SRC / "assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
    H, W = img.shape[:2]
    out = []
    out.append("原图 %dx%d   搜索半径 %d   DT 阈值 %.0f" % (W, H, RAD, DT_THR))
    out.append("（尺寸 = 2×DT，方块越大 DT 越大；实心 128 方块 DT≈50~64）")

    for line in lines:
        lid = str(line.get("id"))
        r, g, b = hex2rgb(line.get("color", "#888888"))
        seq = [s for s in (line.get("stations") or []) if s in stations]
        if len(seq) < 2:
            continue
        for end_i in (0, -1):
            nm = seq[end_i]
            x, y = line_station_xy(stations[nm], lid)
            x0, y0 = max(0, int(x) - RAD), max(0, int(y) - RAD)
            x1, y1 = min(W, int(x) + RAD), min(H, int(y) + RAD)
            sub = img[y0:y1, x0:x1]
            m = (np.abs(sub[:, :, 0] - r) + np.abs(sub[:, :, 1] - g)
                 + np.abs(sub[:, :, 2] - b)) <= 30
            found = blobs(m)
            if not found:
                out.append("%-4s %-8s ✗ 附近没有大块实心区" % (lid, nm))
                continue
            for cy0, cx0, w, h, d in found[:3]:
                px, py = x0 + cx0, y0 + cy0
                dx, dy = px - x, py - y
                dist = (dx * dx + dy * dy) ** 0.5
                if abs(dx) >= abs(dy):
                    ux, uy = (1.0 if dx > 0 else -1.0), 0.0
                else:
                    ux, uy = 0.0, (1.0 if dy > 0 else -1.0)
                out.append("%-4s %-8s 中心(%4.0f,%4.0f) 偏移(%+5.0f,%+5.0f) 距离%5.0f "
                           "方向(%+.0f,%+.0f) 尺寸%3.0fx%-3.0f DT%4.1f"
                           % (lid, nm, px, py, dx, dy, dist, ux, uy, w, h, d))

    txt = "\n".join(out)
    (SRC / "logs" / "_badges_measure.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
