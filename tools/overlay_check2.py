"""原图（淡化） + 程序画的线（加深）叠加，用来核对是否贴合。"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parent.parent
ref = Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")
ours = Image.open(SRC / "lines_octi.png").convert("RGB")
W = 1500
r = ref.resize((W, int(ref.height * W / ref.width)), Image.LANCZOS)
o = ours.resize((W, int(ours.height * W / ours.width)), Image.LANCZOS)

# 我们的线图：白底彩线 → 提取彩色像素
a = np.array(o).astype(np.int16)
mx = a.max(axis=2); mn = a.min(axis=2)
colored = (mx - mn) > 30
bg = np.array(r).astype(np.float32)
bg = bg * 0.30 + 255 * 0.70          # 淡化原图
bg[colored] = np.array(o).astype(np.float32)[colored]
out = Image.fromarray(bg.astype("uint8"))
out = out.crop((0, 0, W, min(out.height, r.height)))
out.save(SRC / "_overlay_v22.png")
print("saved", out.size)
