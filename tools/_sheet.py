# -*- coding: utf-8 -*-
"""只读：把多个换乘站局部裁剪拼成一张总览大图，输出 logs/_sheet.png。
用法: python tools/_sheet.py
"""
from PIL import Image, ImageDraw, ImageFont

try:
    FONT = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
except Exception:
    FONT = ImageFont.load_default()

SRC = "C:/software/subway/源码"
img = Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")

# (标签, 中心x, 中心y)
ITEMS = [
    ("前海湾 1/5/11 横125", 989, 5098),
    ("车公庙 1/7/9/11 横124", 2814, 5374),
    ("福民 4/7/10 横115", 3565, 5724),
    ("国展北 12/20 横75", 440, 2095),
    ("后海 2/11/13 横75+竖108", 1740, 5890),
    ("大运 3/14/16 横48", 5727, 3112),
    ("机场东 1/12 横86", 895, 3026),
    ("光明 6/6支 横75", 2780, 1351),
    ("市民中心 2/4 横47", 3415, 5124),
    ("海上世界 2/12 横48", 1202, 6599),
    ("科学馆 1/6 横48", 4258, 5374),
    ("国展 12/20 横75", 440, 2300),
    ("老街 1/3 竖74", 4766, 4849),
    ("大剧院 1/2/5 竖112", 4613, 5077),
    ("岗厦北 2/10/11/14 竖138", 3715, 5122),
    ("黄贝岭 2/5 竖112", 5141, 5078),
    ("松岗 6/11/12 竖48", 926, 1224),
    ("福田 2/3/11 竖74", 3115, 5149),
    ("红树湾南 9/11 竖74", 2205, 5899),
    ("东角头 2/13 竖74", 1598, 6624),
    ("科苑 2/13 竖48", 1765, 5769),
    ("田贝 3/7 竖48", 4914, 4449),
    ("五和 5/10 竖48", 3715, 3549),
    ("孖岭 9/10 竖48", 3715, 4299),
]

HALF = 130
SCALE = 2
TILE = HALF * 2 * SCALE
COLS = 4
PAD = 6
LBL = 26

rows = (len(ITEMS) + COLS - 1) // COLS
W = COLS * TILE + (COLS + 1) * PAD
H = rows * (TILE + LBL) + (rows + 1) * PAD
sheet = Image.new("RGB", (W, H), (250, 250, 252))
dr = ImageDraw.Draw(sheet)

for idx, (name, cx, cy) in enumerate(ITEMS):
    r, c = divmod(idx, COLS)
    x0 = PAD + c * (TILE + PAD)
    y0 = PAD + r * (TILE + LBL + PAD) + LBL
    box = (max(0, cx - HALF), max(0, cy - HALF), min(img.width, cx + HALF), min(img.height, cy + HALF))
    t = img.crop(box).resize((TILE, TILE), Image.LANCZOS)
    sheet.paste(t, (x0, y0))
    dr.rectangle([x0, y0, x0 + TILE - 1, y0 + TILE - 1], outline=(200, 200, 205))
    dr.text((x0 + 2, y0 - LBL + 4), name, fill=(20, 20, 20), font=FONT)

sheet.save(SRC + "/logs/_sheet.png")
print("saved", sheet.size, "tiles", len(ITEMS))
