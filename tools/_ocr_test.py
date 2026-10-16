import time
from pathlib import Path
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

SRC = Path(__file__).resolve().parent.parent
full = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB"))

print("初始化引擎...")
t0 = time.time()
try:
    eng = RapidOCR(det_limit_side_len=1600, det_limit_type="max")
except TypeError as e:
    print("参数不被支持，用默认:", e)
    eng = RapidOCR()
print("引擎就绪 %.1fs" % (time.time() - t0))

# 取一块 1500x1500 试
x0, y0, S = 3200, 4000, 1500
tile = full[y0:y0 + S, x0:x0 + S]
t0 = time.time()
res, elapse = eng(tile)
print("耗时 %.2fs  识别到 %d 条" % (time.time() - t0, len(res or [])))
for box, text, score in (res or [])[:40]:
    xs = [p[0] for p in box]; ys = [p[1] for p in box]
    print(f"  ({int(min(xs))+x0:>5},{int(min(ys))+y0:>5})  {score:.2f}  {text}")
