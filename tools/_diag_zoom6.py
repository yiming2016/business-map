# -*- coding: utf-8 -*-
"""只读诊断 3：把用户点名的 6 段放大 3.5 倍实拍，看"我的线"在官方带子里是否居中。

上一张图太小看不出 3~6px 的偏移。这里每段裁小窗放大，画我的线（品红细线 2px），
官方带子 22px ⇒ 放大后 77px，偏 5px 就是 17px 的偏心，一眼可见。

用法：python tools/_diag_zoom6.py
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))
import core.data_manager as CDM
CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"
from ui.map_view import build_line_points_ex, line_station_xy
from ui import metro_render as MR

OFF_IM = Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")
OFF = np.asarray(OFF_IM).astype(np.int16)

dm = CDM.get_data_manager()
st = dm.all_stations()
doc = dm.lines_doc
lines = {str(L.get("id")): L for L in (doc.get("lines") or [])}

SEGS = [("12", "福海西", "国展北"), ("12", "国展北", "海上田园南"),
        ("11", "桥头", "福永"), ("11", "宝安", "前海湾"),
        ("11", "后海", "红树湾南"), ("5", "前海湾", "临海")]
ZOOM = 3.5
CELL = 520


def land(nm, lid):
    s = st[nm]
    x, y = line_station_xy(s, lid)
    d = (s.get("lanes") or {}).get(lid)
    if d:
        try:
            x, y = float(x) + float(d[0]), float(y) + float(d[1])
        except Exception:
            pass
    return (float(x), float(y))


def drawn_polyline(lid):
    L = lines[lid]
    seq = [n for n in (L.get("stations") or []) if n in st]
    pts, ebl = build_line_points_ex(lid, seq, st)
    w = MR.octilinear_waypoints_tagged(pts, ebl)
    return [(float(p.x()), float(p.y())) for p, _ in w]


try:
    F = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
except Exception:
    F = ImageFont.load_default()

tiles = []
for lid, a, b in SEGS:
    poly = drawn_polyline(lid)
    A, B = land(a, lid), land(b, lid)
    ia = int(np.argmin([np.hypot(x - A[0], y - A[1]) for x, y in poly]))
    ib = int(np.argmin([np.hypot(x - B[0], y - B[1]) for x, y in poly]))
    if ia > ib:
        ia, ib = ib, ia
    seg = poly[ia:ib + 1]
    if len(seg) < 2:
        seg = [A, B]

    xs = [p[0] for p in seg]
    ys = [p[1] for p in seg]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys)) + 120
    half = span / 2
    s = min(ZOOM, (CELL - 20) / span)          # ★ 整段必须装进格子里

    crop = OFF_IM.crop((int(cx - half), int(cy - half), int(cx + half), int(cy + half)))
    px_w = max(2, int(span * s))
    tile = crop.resize((px_w, px_w), Image.LANCZOS)
    dr = ImageDraw.Draw(tile)
    P = [((x - (cx - half)) * s, (y - (cy - half)) * s) for x, y in seg]
    dr.line(P, fill=(255, 0, 255), width=3, joint="curve")
    for x, y in P:
        dr.ellipse([x - 4, y - 4, x + 4, y + 4], outline=(255, 0, 255), width=2)
    dr.text((6, 6), "x%.2f" % s, fill=(200, 200, 210), font=F)
    tiles.append((lid, a, b, tile, (cx, cy)))

cols = 3
rows = (len(tiles) + cols - 1) // cols
W = cols * CELL + (cols - 1) * 8
H = rows * (CELL + 26) + 8
canvas = Image.new("RGB", (W, H), (240, 240, 244))
for i, (lid, a, b, tile, center) in enumerate(tiles):
    r, c = divmod(i, cols)
    x0, y0 = c * (CELL + 8), r * (CELL + 26) + 26
    th = tile.crop((0, 0, min(CELL, tile.width), min(CELL, tile.height)))
    canvas.paste(th, (x0, y0))
    dr = ImageDraw.Draw(canvas)
    dr.rectangle([x0, y0 - 24, x0 + CELL, y0 - 2], fill=(25, 25, 30))
    dr.text((x0 + 6, y0 - 22), "%s号线 %s->%s  ×%.1f" % (lid, a, b, ZOOM),
            fill=(255, 255, 255), font=F)

out = ROOT / "贴合放大_用户6段_3p5x.png"
canvas.save(out)
print("已出图:", out, canvas.size)
