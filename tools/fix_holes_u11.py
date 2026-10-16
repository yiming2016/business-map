# -*- coding: utf-8 -*-
"""u11 白洞法锚位修复（文锦同款思路的稳健版）。

在锚位周围 160×160 块里找「被带色完全包住的白洞」（官方站洞，直径 ~25px），
洞质心 = 真锚位。只修 |Δ|>3px 的站，全部是单线站 ⇒ 直接动 x/y。
换乘站（老街/红树湾南）不在此列 —— 它们的锚位目检没问题。

附带产出：每站一张掩膜目检图（红十=旧锚位，绿十=洞心）。
★ 已关 exe；写 源码/data/stations.json。
"""
import json
import math
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_dilation, label

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ST_FILE = DATA / "stations.json"
OFF_IMG = Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")
OFF = np.asarray(OFF_IMG, dtype=np.int16)

COLORS = {
    "3": (0, 160, 208),
    "9": (128, 96, 112),
    "10": (247, 117, 148),      # ★ 官方 10 号线真色（色表里的 #E01010 是错的）
}
TOL = 60

# (站名, 线号)
FIXES = [
    ("下梅林", "9"), ("梅村", "9"), ("高新南", "9"), ("深湾", "9"),
    ("晒布", "3"),
    ("岗头", "10"), ("雪象", "10"), ("甘坑", "10"), ("凉帽山", "10"),
    ("上李朗", "10"), ("华为", "10"),
]

HALF = 80
MIN_AREA, MAX_AREA = 220, 1100       # 站洞面积 π·12²≈450，放宽到 220~1100


def find_hole(ax, ay, lid, viz=False):
    c = np.array(COLORS[lid], dtype=np.int16)
    x0, y0 = int(ax - HALF), int(ay - HALF)
    blk = OFF[y0:y0 + 2 * HALF, x0:x0 + 2 * HALF]
    m = (np.abs(blk - c).sum(axis=2) < TOL)
    # 白洞 = 接近纯白且不与带色相邻的外部白连通（先取全白，再要求被带包住）
    white = (blk.min(axis=2) > 235)
    lab, n = label(white)
    best = None
    H, W = m.shape
    m_dil = binary_dilation(m, iterations=2)
    for i in range(1, n + 1):
        cc = (lab == i)
        area = int(cc.sum())
        if not (MIN_AREA <= area <= MAX_AREA):
            continue
        ys, xs = np.nonzero(cc)
        # 洞不能贴块边（贴边=外面的大片背景）
        if xs.min() < 2 or ys.min() < 2 or xs.max() >= W - 2 or ys.max() >= H - 2:
            continue
        # 洞周围必须基本是带色（膨胀 2 圈后 band 覆盖率 > 55%）
        ring = binary_dilation(cc, iterations=4) & ~cc
        cov = float(m[ring].mean()) if ring.any() else 0.0
        if cov < 0.55:
            continue
        cx, cy = float(xs.mean()), float(ys.mean())
        d = math.hypot(cx + x0 - ax, cy + y0 - ay)
        # 圆度：面积 vs 外接圆
        h_w = xs.max() - xs.min() + 1
        h_h = ys.max() - ys.min() + 1
        if max(h_w, h_h) > 40:
            continue
        if best is None or d < best[0]:
            best = (d, cx + x0, cy + y0, area, cov, (cc, x0, y0) if viz else None)
    return best


def main():
    apply_ = "--apply" in sys.argv
    ST = json.loads(ST_FILE.read_text(encoding="utf-8"))
    SMS = ST["stations"]
    rows = []
    for name, lid in FIXES:
        s = SMS[name]
        ax, ay = float(s["x"]), float(s["y"])
        r = find_hole(ax, ay, lid, viz=True)
        if r is None:
            print("[跳] %-5s(%s) 找不到可信白洞" % (name, lid))
            continue
        d, hx, hy, area, cov, vizd = r
        dx, dy = hx - ax, hy - ay
        rows.append((name, lid, dx, dy, hx, hy, vizd))
        flag = "★修" if math.hypot(dx, dy) > 3.0 else "ok"
        print("[量] %-5s(%s) 洞=(%.1f,%.1f) Δ=(%+.1f,%+.1f) |%.1f| 面积=%d 带覆盖率=%.2f %s" % (
            name, lid, hx, hy, dx, dy, d, area, cov, flag))
        # 目检图
        if vizd is not None:
            cc, x0, y0 = vizd
            img = Image.new("RGB", (2 * HALF, 2 * HALF), (30, 30, 30))
            band = (np.abs(OFF[y0:y0 + 2 * HALF, x0:x0 + 2 * HALF] - np.array(COLORS[lid], dtype=np.int16)).sum(axis=2) < TOL)
            base = np.zeros((2 * HALF, 2 * HALF, 3), dtype=np.uint8)
            base[band] = np.array(COLORS[lid], dtype=np.uint8)
            base[cc] = (255, 255, 255)
            img = Image.fromarray(base)
            dr = ImageDraw.Draw(img)
            ox, oy = ax - x0, ay - y0
            dr.line([(ox - 9, oy), (ox + 9, oy)], fill=(255, 0, 0), width=2)
            dr.line([(ox, oy - 9), (ox, oy + 9)], fill=(255, 0, 0), width=2)
            gx, gy = hx - x0, hy - y0
            dr.line([(gx - 9, gy), (gx + 9, gy)], fill=(0, 255, 0), width=2)
            dr.line([(gx, gy - 9), (gx, gy + 9)], fill=(0, 255, 0), width=2)
            img.save(ROOT / "logs" / ("_hole11_%s_%s.png" % (lid, name)))
    if not apply_:
        print("（预演，--apply 生效）")
        return 0
    move = [r for r in rows if math.hypot(r[2], r[3]) > 3.0]
    if not move:
        print("没有需要修的锚位。")
        return 0
    bak = DATA / ("stations.json.bak_hole11_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(ST_FILE, bak)
    print("[备份] %s" % bak.name)
    for name, lid, dx, dy, hx, hy, _ in move:
        s = SMS[name]
        s["x"] = round(hx, 1)
        s["y"] = round(hy, 1)
        print("[改] %-5s (%s, %s) → (%s, %s)" % (name, s["x"], s["y"], round(hx, 1), round(hy, 1)))
    tmp = ST_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ST, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ST_FILE)
    print("[写入] %s" % ST_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
