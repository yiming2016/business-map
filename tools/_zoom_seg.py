# -*- coding: utf-8 -*-
"""把指定的段放大实拍（官方原图 + 软件画的线），用来核对数字是否可信。

用法：python tools/_zoom_seg.py "1|国贸|罗湖" "9|向西村|文锦" ...
"""
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
from ui.map_view import build_line_points_ex
from ui import metro_render as MR

OFF_IM = Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")
dm = CDM.get_data_manager()
ST = dm.all_stations()
LINES = {str(L.get("id")): L for L in (dm.lines_doc.get("lines") or [])}


def corridor_xy(st, lid):
    x, y = float(st.get("x", 0)), float(st.get("y", 0))
    for b in (st.get("alt_bodies") or []):
        if str(b.get("line") or "") == str(lid):
            try:
                x, y = float(b["x"]), float(b["y"])
            except Exception:
                break
    d = (st.get("lanes") or {}).get(str(lid))
    if d:
        try:
            x, y = x + float(d[0]), y + float(d[1])
        except Exception:
            pass
    return (x, y)


def drawn(lid):
    L = LINES[lid]
    seq = [n for n in (L.get("stations") or []) if n in ST]
    pts, ebl = build_line_points_ex(lid, seq, ST)
    return [(float(p.x()), float(p.y())) for p, _ in MR.octilinear_waypoints_tagged(pts, ebl)]


try:
    F = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
except Exception:
    F = ImageFont.load_default()

CELL, COLW = 470, 3
tiles = []
for arg in sys.argv[1:]:
    lid, a, b = arg.split("|")
    poly = drawn(lid)
    A = corridor_xy(ST[a], lid)
    B = corridor_xy(ST[b], lid)
    ia = int(np.argmin([np.hypot(x - A[0], y - A[1]) for x, y in poly]))
    ib = int(np.argmin([np.hypot(x - B[0], y - B[1]) for x, y in poly]))
    if ia > ib:
        ia, ib = ib, ia
    seg = poly[ia:ib + 1]
    if len(seg) < 2:
        seg = [A, B]
    xs = [p[0] for p in seg] + [A[0], B[0]]
    ys = [p[1] for p in seg] + [A[1], B[1]]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys)) + 140
    half = span / 2
    s = min(3.5, (CELL - 20) / span)
    crop = OFF_IM.crop((int(cx - half), int(cy - half), int(cx + half), int(cy + half)))
    pw = max(2, int(span * s))
    tile = crop.resize((pw, pw), Image.LANCZOS)
    dr = ImageDraw.Draw(tile)
    P = [((x - (cx - half)) * s, (y - (cy - half)) * s) for x, y in seg]
    dr.line(P, fill=(255, 0, 255), width=2, joint="curve")
    dr.ellipse([P[0][0] - 5, P[0][1] - 5, P[0][0] + 5, P[0][1] + 5], outline=(255, 0, 0), width=2)
    dr.ellipse([P[-1][0] - 5, P[-1][1] - 5, P[-1][0] + 5, P[-1][1] + 5], outline=(0, 0, 255), width=2)
    tiles.append((arg, tile))

rows = (len(tiles) + COLW - 1) // COLW
W = COLW * CELL + (COLW - 1) * 8
H = rows * (CELL + 26) + 8
canvas = Image.new("RGB", (W, H), (240, 240, 244))
for i, (lab, tile) in enumerate(tiles):
    r, c = divmod(i, COLW)
    x0, y0 = c * (CELL + 8), r * (CELL + 26) + 26
    canvas.paste(tile.crop((0, 0, min(CELL, tile.width), min(CELL, tile.height))), (x0, y0))
    dr = ImageDraw.Draw(canvas)
    dr.rectangle([x0, y0 - 24, x0 + CELL, y0 - 2], fill=(25, 25, 30))
    dr.text((x0 + 6, y0 - 22), "%s  (红=起 蓝=讫)" % lab, fill=(255, 255, 255), font=F)
out = ROOT / "_zoom_seg.png"
canvas.save(out)
print("已出图:", out, canvas.size)
