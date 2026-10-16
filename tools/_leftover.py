"""找出"还没被任何站点占用"的白色标记，并列出它旁边的 OCR 文本。"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage
SRC = Path(__file__).resolve().parent.parent
img = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB"))
st = json.loads((SRC/"data/stations.json").read_text(encoding="utf-8"))["stations"]
labs = json.loads((SRC/"data/ocr_labels.json").read_text(encoding="utf-8"))

white = img.min(axis=2) >= 235
lab, n = ndimage.label(white, structure=np.ones((3,3),int))
print("白色连通域:", n)
sizes = ndimage.sum_labels(np.ones_like(lab), lab, index=np.arange(1, n+1))
slices = ndimage.find_objects(lab)
cands = []
for i, sl in enumerate(slices):
    a = sizes[i]
    if a < 200 or a > 3000: continue
    ys, xs = sl
    w = xs.stop - xs.start; h = ys.stop - ys.start
    if min(w,h) < 14 or max(w,h) > 90: continue
    if a / float(w*h) < 0.55: continue
    cands.append(((xs.start+xs.stop)/2.0, (ys.start+ys.stop)/2.0, int(a), w, h))
print("白色标记候选:", len(cands))

pos = np.array([(s["x"], s["y"]) for s in st.values()])
left = []
for cx, cy, a, w, h in cands:
    if cy > 7150: continue
    d = np.sqrt(((pos[:,0]-cx)**2 + (pos[:,1]-cy)**2).min())
    if d > 26: left.append((cx, cy, a, w, h, float(d)))
print("未被占用的:", len(left))
lp = np.array([(l['x']+l['w']/2, l['y']+l['h']/2) for l in labs])
for cx, cy, a, w, h, d in sorted(left, key=lambda r: r[1]):
    dd = np.sqrt((lp[:,0]-cx)**2 + (lp[:,1]-cy)**2)
    idx = np.argsort(dd)[:3]
    print(f"  ({cx:>7.1f},{cy:>7.1f}) {w}×{h} a={a} 最近站距{d:>5.0f}  附近OCR:{[labs[i]['text'] for i in idx]}")
