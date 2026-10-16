# -*- coding: utf-8 -*-
"""只读：高倍放大指定站点，拼成一张图 logs/_sheet2.png。
用法: python tools/_sheet2.py
"""
from PIL import Image, ImageDraw, ImageFont

SRC = "C:/software/subway/源码"
img = Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")
try:
    FONT = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 22)
except Exception:
    FONT = ImageFont.load_default()

# 重点疑点站
ITEMS = [
    ("科苑 横竖? 2/13", 1765, 5769),
    ("光明 横 6/6支(端点)", 2780, 1351),
    ("国展北 横 12/20", 440, 2095),
    ("机场东 横 1(端点)/12", 895, 3026),
    ("机场北 竖 11/20", 639, 3014),
    ("太安 竖 5/7", 5214, 4449),
    ("田贝 竖 3/7", 4914, 4449),
    ("松岗 竖 6(端点)/11/12", 926, 1224),
    ("老街 竖 1/3", 4766, 4849),
    ("大剧院 竖 1/2/5", 4613, 5077),
    ("前海湾 横 1/5/11", 989, 5098),
    ("黄贝岭 竖 2/5", 5141, 5078),
]

HALF = 105
SCALE = 4
TILE = HALF * 2 * SCALE
COLS = 3
PAD = 8
LBL = 30

rows = (len(ITEMS) + COLS - 1) // COLS
W = COLS * TILE + (COLS + 1) * PAD
H = rows * (TILE + LBL) + (rows + 1) * PAD
sheet = Image.new("RGB", (W, H), (248, 248, 250))
dr = ImageDraw.Draw(sheet)

for idx, (name, cx, cy) in enumerate(ITEMS):
    r, c = divmod(idx, COLS)
    x0 = PAD + c * (TILE + PAD)
    y0 = PAD + r * (TILE + LBL + PAD) + LBL
    box = (max(0, cx - HALF), max(0, cy - HALF), min(img.width, cx + HALF), min(img.height, cy + HALF))
    t = img.crop(box).resize((TILE, TILE), Image.LANCZOS)
    sheet.paste(t, (x0, y0))
    dr.rectangle([x0, y0, x0 + TILE - 1, y0 + TILE - 1], outline=(190, 190, 196))
    dr.text((x0 + 3, y0 - LBL + 4), name, fill=(15, 15, 15), font=FONT)

sheet.save(SRC + "/logs/_sheet2.png")
print("saved", sheet.size)
