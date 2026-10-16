import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))
from tools.rederive_order import LEGEND, TOL, DILATE

img = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)
st = json.loads((SRC/"data/stations.json").read_text(encoding="utf-8"))["stations"]
lj = json.loads((SRC/"data/lines.json").read_text(encoding="utf-8"))["lines"]
labs = json.loads((SRC/"data/ocr_labels.json").read_text(encoding="utf-8"))

def nest_labels(x, y, r=170):
    return sorted([l for l in labs if abs(l['x']+l['w']/2-x)<r and abs(l['y']+l['h']/2-y)<r],
                  key=lambda l: (l['x']+l['w']/2-x)**2+(l['y']+l['h']/2-y)**2)

lid = sys.argv[1] if len(sys.argv)>1 else "9"
c = np.array(LEGEND[lid], dtype=np.int16)
m = (np.abs(img - c).max(axis=2) <= TOL)
dil = ndimage.binary_dilation(m, iterations=8)
print(f"{lid} 号线掩膜像素 {int(m.sum())}")

ln = [l for l in lj if l["id"]==lid][0]
declared = set(s for s in ln["stations"] if s in st)
print("声明站点数:", len(declared))

print("\n落在走廊上的站点坐标（按最近站名整理）:")
on = []
for sid, s in st.items():
    x, y = int(s["x"]), int(s["y"])
    if 0<=y<dil.shape[0] and 0<=x<dil.shape[1] and dil[y, x]:
        on.append((sid, s))
print(" 共", len(on), "个")
for sid, s in on:
    mark = "" if sid in declared else "  ←不在声明里"
    print(f"   {sid:<8} ({s['x']:>7.1f},{s['y']:>7.1f}){mark}")

print("\n声明了但不在走廊上的站点:")
for sid in declared:
    s = st[sid]; x, y = int(s["x"]), int(s["y"])
    ok = 0<=y<dil.shape[0] and 0<=x<dil.shape[1] and dil[y, x]
    if not ok:
        near = nest_labels(s['x'], s['y'])[:3]
        print(f"   {sid:<8} ({s['x']:>7.1f},{s['y']:>7.1f})  附近OCR:{[l['text'] for l in near]}")
