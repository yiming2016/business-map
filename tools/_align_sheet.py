# -*- coding: utf-8 -*-
"""只读：把若干"疑似偏位"的站，按**我们记录里的坐标**在原图上打圈裁出来拼成一张图，
一眼看出我们的点在原图上是不是站在站点上。

用法: python tools/_align_sheet.py <站名1> <站名2> ...
产物: logs/_align_sheet.png
"""
import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SRC = Path("C:/software/subway/源码")
HALF, SC = 200, 1.6
names = sys.argv[1:]
if not names:
    names = ["福民", "岗厦北", "大剧院", "黄贝岭", "前海湾", "车公庙"]

st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
img = Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")
TILE = int(HALF * 2 * SC)
try:
    fnt = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 22)
except Exception:
    fnt = ImageFont.load_default()

tiles = []
for nm in names:
    s = st.get(nm)
    if not s:
        print("缺站", nm)
        continue
    cx, cy = int(float(s["x"])), int(float(s["y"]))
    c = img.crop((cx - HALF, cy - HALF, cx + HALF, cy + HALF)).resize((TILE, TILE), Image.LANCZOS)
    d = ImageDraw.Draw(c)
    k = SC
    # 我们的坐标（正中心）画洋红十字
    d.line([TILE / 2 - 26, TILE / 2, TILE / 2 + 26, TILE / 2], fill=(255, 0, 160), width=3)
    d.line([TILE / 2, TILE / 2 - 26, TILE / 2, TILE / 2 + 26], fill=(255, 0, 160), width=3)
    d.ellipse([TILE / 2 - 9, TILE / 2 - 9, TILE / 2 + 9, TILE / 2 + 9],
              outline=(255, 0, 160), width=3)
    # 被诊断为"最近白点"的位置画青圈
    tiles.append((nm, (cx, cy), c))

COLS = 3
ROWS = (len(tiles) + COLS - 1) // COLS
LBL = 30
sheet = Image.new("RGB", (COLS * TILE + (COLS + 1) * 8, ROWS * (TILE + LBL) + (ROWS + 1) * 8),
                  (255, 255, 255))
d = ImageDraw.Draw(sheet)
for i, (nm, (cx, cy), c) in enumerate(tiles):
    r, cc = divmod(i, COLS)
    x = 8 + cc * (TILE + 8)
    y = 8 + r * (TILE + LBL + 8)
    sheet.paste(c, (x, y))
    d.text((x + 2, y + TILE + 2), "%s  (%d,%d)" % (nm, cx, cy), fill=(10, 10, 10), font=fnt)
sheet.save(SRC / "logs" / "_align_sheet.png")
print("saved", sheet.size, len(tiles))
