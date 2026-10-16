"""从原图左下角图例中自动识别每条线路的官方颜色（连通域 + 主色）。"""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = Path(__file__).resolve().parent.parent
full = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB"))
BOX = (160, 7280, 3520, 8000)          # 图例区域 (x0,y0,x1,y1)
sub = full[BOX[1]:BOX[3], BOX[0]:BOX[2]].astype(np.int16)

mx = sub.max(axis=2); mn = sub.min(axis=2)
sat = mx - mn
mask = (sat > 45) & (mx > 70)          # 有颜色的像素
lab, n = ndimage.label(mask, structure=np.ones((3, 3), int))
print("连通域数:", n)

rows = []
for i in range(1, n + 1):
    ys, xs = np.where(lab == i)
    if len(ys) < 400:
        continue
    h = ys.max() - ys.min() + 1
    w = xs.max() - xs.min() + 1
    if h > 70:                          # 太高的可能是线条/装饰
        continue
    px = sub[ys, xs]
    c = np.median(px, axis=0).astype(int)
    rows.append((int(ys.mean()), int(xs.mean()), w, h, len(ys),
                 "#%02X%02X%02X" % tuple(int(v) for v in c)))

rows.sort(key=lambda r: (r[0] // 60, r[1]))
for r in rows:
    print(f"y={r[0]:>4} x={r[1]:>4} w={r[2]:>4} h={r[3]:>3} n={r[4]:>6}  {r[5]}")
