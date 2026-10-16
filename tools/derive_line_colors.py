"""
tools/derive_line_colors.py
================================
从原图反推每条线路**真实使用的颜色**。

背景：lines.json 里的颜色是当初看图例肉眼记的，和原图实际画的颜色对不上
（例如 9 号线记的是 #8B6C42，原图里根本没有这种颜色）。

做法（最可靠的一条路）：
  普通站的圆点描边用的就是**它所属线路的颜色**。所以：
    1. 在原图里找出所有站点标记，并取白斑外圈的描边色
    2. 按坐标把标记匹配到站点；只取"只属于一条线"的普通站
    3. 同一线路的所有描边色取中位数 = 该线路真实颜色

用法：
    python tools/derive_line_colors.py
    python tools/derive_line_colors.py --fix
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

REGION = (50, 600, 7950, 7000)
MIN_AREA, MAX_AREA = 120, 3500
MIN_SIDE, MAX_SIDE = 11, 60
WHITE_MIN = 225
RING_PAD = 12
MATCH_DIST = 60.0


def hex_to_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def detect(img):
    L, T, R, B = REGION
    a = np.asarray(img.crop((L, T, R, B))).astype(np.int16)
    h, w = a.shape[:2]
    ink = a.min(axis=2) < 200
    lab, _ = ndimage.label(~ink)
    objs = ndimage.find_objects(lab)
    sat = (a.max(axis=2) - a.min(axis=2)) > 45

    out = []
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        bh, bw = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if not (MIN_SIDE <= bw <= MAX_SIDE and MIN_SIDE <= bh <= MAX_SIDE):
            continue
        m = (lab[sl] == i)
        area = int(m.sum())
        if not (MIN_AREA <= area <= MAX_AREA):
            continue
        if a[sl][m].min(axis=1).mean() < WHITE_MIN:
            continue
        if area / (bw * bh) < 0.62:
            continue
        y0, y1 = max(0, sl[0].start - RING_PAD), min(h, sl[0].stop + RING_PAD)
        x0, x1 = max(0, sl[1].start - RING_PAD), min(w, sl[1].stop + RING_PAD)
        rs = sat[y0:y1, x0:x1]
        pts = a[y0:y1, x0:x1][rs]
        out.append({
            "x": float(sl[1].start + bw / 2 + L),
            "y": float(sl[0].start + bh / 2 + T),
            "ring": tuple(int(v) for v in np.median(pts, axis=0)) if len(pts) >= 20 else None,
            "n_ring": int(len(pts)),
        })
    return out


def main():
    do_fix = "--fix" in sys.argv

    img = Image.open(ORIGINAL).convert("RGB")
    cands = detect(img)
    print(f"检测到站点标记: {len(cands)}")

    stations = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
    lines_doc = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))

    # 把标记按坐标贴到站点上
    per_line = {}
    for c in cands:
        if c["ring"] is None or c["n_ring"] < 40:
            continue
        best, bd = None, 1e9
        for sid, s in stations.items():
            d = math.hypot(float(s["x"]) - c["x"], float(s["y"]) - c["y"])
            if d < bd:
                bd, best = d, sid
        if best is None or bd > MATCH_DIST:
            continue
        lid = stations[best].get("lines") or []
        # 只用"单线站"（多线站的描边是深灰，不是线路色）
        if len(lid) != 1:
            continue
        per_line.setdefault(lid[0], []).append(c["ring"])

    print(f"\n{'线路':<18} {'样本':>4} {'当前颜色':>9} {'实测颜色':>9} {'色差':>7}")
    print("-" * 58)
    mapping = {}
    for ln in lines_doc["lines"]:
        samples = per_line.get(ln["id"], [])
        if not samples:
            print(f"{ln.get('name',''):<18} {'0':>4} {'—':>9} {'无样本':>9}")
            continue
        arr = np.array(samples, dtype=float)
        med = np.median(arr, axis=0)
        rgb = tuple(int(round(v)) for v in med)
        # 剔掉偏离中位数较远的样本后重算
        keep = [s for s in samples if rgb_dist(s, rgb) < 45]
        if keep:
            rgb = tuple(int(round(v)) for v in np.median(np.array(keep, dtype=float), axis=0))
        old = hex_to_rgb(ln.get("color", "#888888"))
        d = rgb_dist(old, rgb)
        mapping[ln["id"]] = rgb
        flag = "" if d < 25 else "  ← 需修正"
        print(f"{ln.get('name',''):<18} {len(samples):>4} "
              f"#{old[0]:02X}{old[1]:02X}{old[2]:02X}   "
              f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X} {d:>7.1f}{flag}")

    if not do_fix:
        print("\n（加 --fix 参数可写回 lines.json）")
        return

    bak = DATA / "lines.json.bak_color"
    if not bak.exists():
        shutil.copy2(DATA / "lines.json", bak)
        print(f"[BACKUP] {bak}")
    n = 0
    for ln in lines_doc["lines"]:
        rgb = mapping.get(ln["id"])
        if not rgb:
            continue
        new = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
        if ln.get("color", "").upper() != new:
            ln["color"] = new
            n += 1
    (DATA / "lines.json").write_text(
        json.dumps(lines_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] 已写回，修正 {n} 条线路的颜色")


if __name__ == "__main__":
    main()
