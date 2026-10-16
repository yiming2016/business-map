# -*- coding: utf-8 -*-
"""只读：把原图局部裁剪放大，输出 logs/_crop.png，供人/模型目视。
用法: python tools/_crop.py <cx> <cy> [half] [scale]
"""
import sys
from PIL import Image

SRC = "C:/software/subway/源码"
cx, cy = int(sys.argv[1]), int(sys.argv[2])
half = int(sys.argv[3]) if len(sys.argv) > 3 else 220
scale = int(sys.argv[4]) if len(sys.argv) > 4 else 2

img = Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")
box = (max(0, cx - half), max(0, cy - half), min(img.width, cx + half), min(img.height, cy + half))
c = img.crop(box)
c = c.resize((c.width * scale, c.height * scale), Image.LANCZOS)
c.save(SRC + "/logs/_crop.png")
print("saved", c.size, "from", box)
