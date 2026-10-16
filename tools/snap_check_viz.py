"""视觉核对 resnap 换乘站定位：裁剪原图，红圈=旧坐标，绿圈=新坐标，
拼成网格图输出 data/_snap_check.png 供人工审阅。"""
import json
import math
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
IMG = SRC / "assets" / "shenzhen_metro.png"

CN = re.compile(r"^[\u4e00-\u9fff]+$")
ALIAS = {"梅林": "梅村", "笋岗洪湖": "笋岗", "念馆": "东纵纪念馆"}

report = (DATA / "_resnap_report.txt").read_text(encoding="utf-8").splitlines()
targets = []
for ln in report:
    m = re.match(r"(\S+)\s+\(\s*([\d.]+),\s*([\d.]+)\) -> \(\s*([\d.]+),\s*([\d.]+)\)\s+位移\s+([\d.]+)", ln)
    if m and float(m.group(6)) >= 120:
        targets.append((m.group(1), float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5)), float(m.group(6))))
print(f"待核对大位移站 {len(targets)} 个")

im = Image.open(IMG).convert("RGB")
cells = []
for (n, ox, oy, nx, ny, sh) in targets:
    cx = (ox + nx) / 2
    cy = (oy + ny) / 2
    half_w = max(abs(ox - nx) / 2 + 260, 330)
    half_h = max(abs(oy - ny) / 2 + 200, 230)
    x0, y0 = int(cx - half_w), int(cy - half_h)
    x1, y1 = int(cx + half_w), int(cy + half_h)
    crop = im.crop((max(x0, 0), max(y0, 0), min(x1, im.width), min(y1, im.height)))
    d = ImageDraw.Draw(crop)
    for (px, py), col, r in [((ox, oy), (230, 30, 30), 16), ((nx, ny), (30, 190, 60), 16)]:
        px, py = px - x0, py - y0
        d.ellipse([px - r, py - r, px + r, py + r], outline=col, width=5)
    d.text((10, 8), f"{n}  shift={sh:.0f}", fill=(0, 0, 255))
    cells.append((n, crop))

# 网格拼图：4 列，拆成多张（每张最多 12 格，避免整图过高被压缩）
COLS = 4
cw = max(c.width for _, c in cells)
ch = max(c.height for _, c in cells)
PER = 12
for part in range((len(cells) + PER - 1) // PER):
    chunk = cells[part * PER:(part + 1) * PER]
    rows = (len(chunk) + COLS - 1) // COLS
    grid = Image.new("RGB", (cw * COLS, ch * rows), (255, 255, 255))
    for i, (n, c) in enumerate(chunk):
        grid.paste(c, ((i % COLS) * cw, (i // COLS) * ch))
    out = DATA / f"_snap_check_{part + 1}.png"
    grid.save(out)
    print(f"拼图 -> {out.name}  ({grid.width}x{grid.height}, {len(chunk)}格)")
