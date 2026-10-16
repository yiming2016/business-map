# -*- coding: utf-8 -*-
"""u11 锚位目检：每个站出两张裁剪图（官方原图 / 带色掩膜），
标出当前锚位（红十）与垂线扫描线（黄线），一眼看出偏到哪。只读。"""
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OFF_IMG = Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")
OFF = np.asarray(OFF_IMG, dtype=np.int16)

COLORS = {"3": (0, 160, 208), "9": (128, 96, 112)}
TOL = 48

FIXES = [
    ("下梅林", "9", 2984.0, 4312.0),
    ("梅村", "9", 3211.0, 4299.0),
    ("高新南", "9", 1920.0, 5666.0),
    ("深湾", "9", 2403.0, 5874.0),
    ("晒布", "3", 4914.0, 4719.0),
    ("老街", "3", 4765.6, 4823.7),
    ("红树湾南", "9", 2205.1, 5882.2),
]

HALF = 60
OUT = ROOT / "logs"
OUT.mkdir(exist_ok=True)

for name, lid, ax, ay in FIXES:
    c = np.array(COLORS[lid], dtype=np.int16)
    x0, y0 = int(ax - HALF), int(ay - HALF)
    x1, y1 = int(ax + HALF), int(ay + HALF)
    blk = OFF[y0:y1, x0:x1]
    m = (np.abs(blk - c).sum(axis=2) < TOL)
    # 掩膜：带=黑底白带，洞=黑
    mask_img = Image.fromarray(np.where(m, 255, 0).astype(np.uint8)).convert("RGB")
    d = ImageDraw.Draw(mask_img)
    # 垂线扫描线（假设走廊水平 → 垂线竖直；仅示意）
    d.line([(HALF, 0), (HALF, 2 * HALF)], fill=(255, 255, 0), width=1)
    # 锚位红十
    d.line([(HALF - 8, HALF), (HALF + 8, HALF)], fill=(255, 0, 0), width=2)
    d.line([(HALF, HALF - 8), (HALF, HALF + 8)], fill=(255, 0, 0), width=2)
    orig = OFF_IMG.crop((x0, y0, x1, y1))
    W, H = 2 * HALF, 2 * HALF
    canvas = Image.new("RGB", (W * 2 + 12, H), (40, 40, 40))
    canvas.paste(orig, (0, 0))
    canvas.paste(mask_img, (W + 12, 0))
    f = OUT / ("_anc11_%s_%s.png" % (lid, name))
    canvas.save(f)
    print(f.name)
