# -*- coding: utf-8 -*-
"""u12 锚位切片量尺：沿走廊垂线切官方带，带边的 min/max 中点 = 中心线。
站洞/药丸（白）夹在带中间时外沿中点仍是带中心 ⇒ 天然免疫站洞。
单线站动 x/y，换乘站只动 lanes[本线] dx/dy。|Δ|>3px 才修。
"""
import json
import math
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ST_FILE = DATA / "stations.json"
OFF = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB"), dtype=np.int16)

COLORS = {
    "9": (128, 96, 112),
    "11": (96, 32, 64),
}
TOL = 60

# (站名, 线号)  单线→动xy；换乘→动lanes
FIXES = [
    ("南油西", "9"),
    ("南油", "9"),
    ("南山书城", "9"),
    ("深大南", "9"),
    ("南山", "11"),
    ("后海", "11"),
]

ST = json.loads(ST_FILE.read_text(encoding="utf-8"))
SMS = ST["stations"]
LN = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))
LINES = {L["id"]: L for L in LN["lines"]}


def anchor_of(name, lid):
    s = SMS[name]
    d = (s.get("lanes") or {}).get(str(lid))
    x, y = float(s["x"]), float(s["y"])
    if d:
        return x + float(d[0]), y + float(d[1]), d
    return x, y, None


def corridor_dir(name, lid):
    s = SMS[name]
    d = (s.get("lanes") or {}).get(str(lid))
    if d and len(d) >= 3 and float(d[3]) >= 3.0:
        a = math.radians(float(d[2]))
        return math.cos(a), math.sin(a)
    seq = [n for n in (LINES[lid].get("stations") or []) if n in SMS]
    i = seq.index(name)
    pts = []
    for j in (i - 1, i + 1):
        if 0 <= j < len(seq):
            qx, qy, _ = anchor_of(seq[j], lid)
            ax, ay, _ = anchor_of(name, lid)
            L = math.hypot(qx - ax, qy - ay)
            if L > 1:
                pts.append(((qx - ax) / L, (qy - ay) / L))
    if not pts:
        return None
    dx = sum(p[0] for p in pts)
    dy = sum(p[1] for p in pts)
    L = math.hypot(dx, dy)
    if L < 1e-6:
        return pts[0]
    return dx / L, dy / L


def band_center_on_slice(ax, ay, px, py, lid, half=32.0, step=0.5):
    """沿垂线切片，返回带色像素的 (tmin+tmax)/2 与命中数。"""
    c = np.array(COLORS[lid], dtype=np.int16)
    ts = np.arange(-half, half + 1e-9, step)
    hits = []
    for t in ts:
        x = int(round(ax + px * t))
        y = int(round(ay + py * t))
        if 0 <= x < OFF.shape[1] and 0 <= y < OFF.shape[0] and \
                np.abs(OFF[y, x] - c).sum() < TOL:
            hits.append(t)
    if not hits:
        return None
    return (hits[0] + hits[-1]) / 2.0, len(hits)


def main():
    apply_ = "--apply" in sys.argv
    rows = []
    for name, lid in FIXES:
        ax, ay, d = anchor_of(name, lid)
        dr = corridor_dir(name, lid)
        if dr is None:
            print("[跳] %s(%s) 方向不明" % (name, lid))
            continue
        dx, dy = dr
        px, py = -dy, dx
        r = band_center_on_slice(ax, ay, px, py, lid)
        if r is None:
            print("[跳] %s(%s) 切片无带色" % (name, lid))
            continue
        t_mid, nhit = r
        width = nhit * 0.5
        ex, ey = px * t_mid, py * t_mid
        dev = math.hypot(ex, ey)
        single = d is None
        rows.append((name, lid, single, ex, ey, dev, width))
        print("[量] %-5s(%s) 锚=(%.1f,%.1f) 带中心偏移=(%+.1f,%+.1f) |%.1f| 切片带宽%.0f %s" % (
            name, lid, ax, ay, ex, ey, dev, width,
            "单线→xy" if single else "换乘→lanes"))
    if not apply_:
        print("（预演）")
        return 0
    move = [r for r in rows if r[5] > 3.0]
    if not move:
        print("无需修。")
        return 0
    bak = DATA / ("stations.json.bak_anc12_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(ST_FILE, bak)
    print("[备份] %s" % bak.name)
    for name, lid, single, ex, ey, dev, w in move:
        s = SMS[name]
        if single:
            s["x"] = round(float(s["x"]) + ex, 1)
            s["y"] = round(float(s["y"]) + ey, 1)
            print("[改] %-5s x/y → (%s, %s)" % (name, s["x"], s["y"]))
        else:
            dd = s["lanes"][lid]
            dd[0] = round(float(dd[0]) + ex, 1)
            dd[1] = round(float(dd[1]) + ey, 1)
            print("[改] %-5s lanes[%s] → (%s, %s)" % (name, lid, dd[0], dd[1]))
    tmp = ST_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ST, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ST_FILE)
    print("[写入] %s" % ST_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
