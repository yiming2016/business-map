# -*- coding: utf-8 -*-
"""只读：把某区域的"白色形状"打成字符画（#=白  .=非白），用来定位站点白圆点。
用法：python tools/_white_view.py x0 y0 x1 y1 [step]
"""
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
x0, y0, x1, y1 = (int(v) for v in sys.argv[1:5])
step = int(sys.argv[5]) if len(sys.argv) > 5 else 4

white = (np.abs(img[:, :, 0] - 254) + np.abs(img[:, :, 1] - 254) + np.abs(img[:, :, 2] - 254)) <= 12
white = ndimage.binary_erosion(white, np.ones((3, 3)))
print(f"白掩膜 x[{x0},{x1}) y[{y0},{y1}) step={step}   #=白  .=非白")
print("      " + "".join(str(((x0 + c * step) // 10) % 10) for c in range((x1 - x0) // step)))
for r in range((y1 - y0) // step):
    yy = y0 + r * step
    line = []
    for c in range((x1 - x0) // step):
        xx = x0 + c * step
        blk = white[yy:yy + step, xx:xx + step]
        line.append("#" if blk.mean() >= 0.5 else ("+" if blk.mean() >= 0.2 else "."))
    print(f"{yy:5d} " + "".join(line))
