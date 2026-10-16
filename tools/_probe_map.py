# -*- coding: utf-8 -*-
"""只读：把原图局部打成字符画（每格 N 像素取众数颜色分类）。"""
import sys
from PIL import Image
img = Image.open("C:/software/subway/源码/assets/shenzhen_metro.png").convert("RGB")
cx, cy, half, cell = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
box = (cx-half, cy-half, cx+half, cy+half)
c = img.crop(box)
w, h = c.width//cell, c.height//cell
px = c.load()
out = []
for j in range(h):
    row = ""
    for i in range(w):
        r=g=b=0; n=0
        for dy in range(cell):
            for dx in range(cell):
                p = px[i*cell+dx, j*cell+dy]
                r+=p[0]; g+=p[1]; b+=p[2]; n+=1
        r//=n; g//=n; b//=n
        if r>235 and g>235 and b>235: ch="."
        elif abs(r-g)<14 and abs(g-b)<14 and 90<=r<=200: ch="G"
        elif r>150 and g<90 and b<90: ch="R"
        elif r>200 and 120<g<190 and b<90: ch="O"
        else: ch="?"
        row += ch
    out.append(row)
print("\n".join(out))
