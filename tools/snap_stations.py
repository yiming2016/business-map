"""
tools/snap_stations.py
================================
把站点坐标自动吸附到原图中检测出的"站点标记"上，修正肉眼读数误差。

流程：
  1. 在原图里找所有小白斑（被描边包围的白块）= 站点标记候选
  2. 对每个候选，取它外圈的颜色（站点标记的描边就是线路色）
  3. 把每个站点与 500 单位内的候选配对，用 (颜色差异, 距离) 打分
  4. 贪心做一对一匹配（一个候选只能给一个站点用）
  5. 匹配上的站点把坐标改成候选位置；没匹配上的原样保留

用法：
    python tools/snap_stations.py            # 只报告 + 出对照图
    python tools/snap_stations.py --fix      # 写回 stations.json（自动备份）
"""

import sys
import json
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

SRC_ROOT = Path(__file__).resolve().parent.parent
DATA = SRC_ROOT / "data"
ORIGINAL = SRC_ROOT / "assets" / "shenzhen_metro.png"

REGION = (50, 600, 7950, 7000)
MIN_AREA, MAX_AREA = 120, 3500
MIN_SIDE, MAX_SIDE = 11, 60
WHITE_MIN = 225
MAX_SNAP_DIST = 400.0
RING_PAD = 12
COLOR_WEIGHT = 0.55   # 总评分 = 距离 + COLOR_WEIGHT × 颜色差（距离为主，颜色防止吸错）


def hex_to_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def detect(img):
    L, T, R, B = REGION
    sub = img.crop((L, T, R, B))
    a = np.asarray(sub).astype(np.int16)
    h, w = a.shape[:2]
    ink = a.min(axis=2) < 200
    lab, n = ndimage.label(~ink)
    objs = ndimage.find_objects(lab)
    sat = (a.max(axis=2) - a.min(axis=2)) > 45

    out = []
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        bh = sl[0].stop - sl[0].start
        bw = sl[1].stop - sl[1].start
        if not (MIN_SIDE <= bw <= MAX_SIDE and MIN_SIDE <= bh <= MAX_SIDE):
            continue
        m = (lab[sl] == i)
        area = int(m.sum())
        if not (MIN_AREA <= area <= MAX_AREA):
            continue
        if a[sl][m].min(axis=1).mean() < WHITE_MIN:
            continue
        fill = area / (bw * bh)
        if fill < 0.62:
            continue

        # 外圈颜色：白斑外扩一圈，取"彩色且不太亮"的像素中位数
        y0 = max(0, sl[0].start - RING_PAD)
        y1 = min(h, sl[0].stop + RING_PAD)
        x0 = max(0, sl[1].start - RING_PAD)
        x1 = min(w, sl[1].stop + RING_PAD)
        ring = a[y0:y1, x0:x1]
        rs = sat[y0:y1, x0:x1]
        pts = ring[rs]
        ring_rgb = None
        if len(pts) >= 20:
            ring_rgb = tuple(int(v) for v in np.median(pts, axis=0))

        out.append({
            "x": float(sl[1].start + bw / 2 + L),
            "y": float(sl[0].start + bh / 2 + T),
            "rgb": ring_rgb,
        })
    return out


def main():
    do_fix = "--fix" in sys.argv

    img = Image.open(ORIGINAL).convert("RGB")
    cands = detect(img)
    print(f"站点标记候选: {len(cands)}")

    doc = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))
    stations = doc["stations"]
    lines_doc = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))
    line_colors = {ln["id"]: hex_to_rgb(ln.get("color", "#888888")) for ln in lines_doc["lines"]}

    # 每个站点允许匹配的颜色集合
    st_colors = {}
    for sid, s in stations.items():
        cols = [line_colors[i] for i in s.get("lines", []) if i in line_colors]
        st_colors[sid] = cols

    pairs = []
    for sid, s in stations.items():
        x, y = float(s["x"]), float(s["y"])
        for ci, c in enumerate(cands):
            d = math.hypot(c["x"] - x, c["y"] - y)
            if d > MAX_SNAP_DIST:
                continue
            if c["rgb"] is not None and st_colors[sid]:
                pen = min(rgb_dist(c["rgb"], col) for col in st_colors[sid])
            elif c["rgb"] is None:
                pen = 90.0                 # 没取到颜色的（多为换乘站黑边）给中性分
            else:
                pen = 90.0
            pairs.append((d + COLOR_WEIGHT * pen, d, sid, ci))

    pairs.sort(key=lambda p: (p[0], p[1]))
    used_sid, used_ci = set(), set()
    assign = {}
    for score, d, sid, ci in pairs:
        if sid in used_sid or ci in used_ci:
            continue
        used_sid.add(sid)
        used_ci.add(ci)
        assign[sid] = (ci, score, d)

    moved = []
    for sid, (ci, score, d) in assign.items():
        if d < 1.0:
            continue
        moved.append((sid, stations[sid].get("station_name", sid), d, score))

    print(f"匹配成功: {len(assign)} / {len(stations)}")
    moved.sort(key=lambda m: -m[2])
    print(f"需要移动的站点: {len(moved)}")
    ds = sorted(m[2] for m in moved)
    if ds:
        print(f"位移分布: 中位={ds[len(ds)//2]:.0f}  90分位={ds[int(len(ds)*0.9)]:.0f}  最大={ds[-1]:.0f}")
    print("\n位移最大的 15 个：")
    for sid, nm, d, score in moved[:15]:
        print(f"   {nm:<10} 位移 {d:6.0f}   综合分 {score:6.0f}")

    far = [m for m in moved if m[2] > 300]
    print(f"\n位移 > 300 的: {len(far)} 个（这些最可能是错误坐标）")

    # 对照图
    side = 1600
    k = side / img.size[0]
    vis = img.resize((side, side), Image.LANCZOS)
    dr = ImageDraw.Draw(vis)
    for sid, s in stations.items():
        ox, oy = float(s["x"]) * k, float(s["y"]) * k
        if sid in assign:
            ci = assign[sid][0]
            nx, ny = cands[ci]["x"] * k, cands[ci]["y"] * k
            dr.line([ox, oy, nx, ny], fill=(0, 160, 255), width=1)
            dr.ellipse([nx - 4, ny - 4, nx + 4, ny + 4], outline=(255, 0, 255), width=2)
        dr.ellipse([ox - 3, oy - 3, ox + 3, oy + 3], outline=(255, 120, 0), width=2)
    vis.save(str(SRC_ROOT / "snap_vis.png"))
    print(f"\n[OK] 对照图 → {SRC_ROOT / 'snap_vis.png'}  (橙=原坐标, 品红=吸附目标, 蓝线=位移)")

    if not do_fix:
        print("（加 --fix 参数可写回 stations.json）")
        return

    bak = DATA / "stations.json.bak_snap"
    if not bak.exists():
        shutil.copy2(DATA / "stations.json", bak)
        print(f"[BACKUP] {bak}")

    for sid, (ci, score, d) in assign.items():
        stations[sid]["x"] = round(cands[ci]["x"], 1)
        stations[sid]["y"] = round(cands[ci]["y"], 1)
    (DATA / "stations.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] 已写回 {DATA / 'stations.json'}，修正 {len(assign)} 个站点坐标")


if __name__ == "__main__":
    main()
